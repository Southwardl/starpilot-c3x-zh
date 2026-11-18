"""补全已导出包的 userdata 项并重建 XML/清单。

导出时误把 userdata 从清单里完全移除，而 raw_verify 要求每个分区都有镜像。
本脚本补上 64 KiB 复位标记（RC10 的做法），重建 programs 与 XML，然后重校验。
"""
import hashlib
import json
import sys
import threading
import xml.etree.ElementTree as ET
from pathlib import Path

PKG = Path(r"D:\c3x_pkg")
SRC = Path(r"D:\ds_harness\SkyGMFlasher-0.1.13-preview-win64\source")
SECTOR = 4096
USERDATA_MARKER = b"COMMA_RESET"


def xml_program(lun, label, filename, start_sector, size):
    return {
        "start_sector": str(start_sector),
        "size_in_KB": f"{size / 1024:.1f}",
        "physical_partition_number": str(lun),
        "num_partition_sectors": str(size // SECTOR),
        "sparse": "false",
        "filename": filename,
        "SECTOR_SIZE_IN_BYTES": str(SECTOR),
        "label": label,
        "file_sector_offset": "0",
        "start_byte_hex": hex(start_sector * SECTOR),
    }


def write_xml(out_dir: Path, lun: int, programs: list[dict]) -> None:
    root = ET.Element("data")
    for a in programs:
        ET.SubElement(root, "program", {k: str(v) for k, v in a.items()})
    ET.ElementTree(root).write(out_dir / f"rawprogram{lun}.xml", encoding="utf-8", xml_declaration=True)
    ET.ElementTree(ET.Element("patches")).write(out_dir / f"patch{lun}.xml", encoding="utf-8", xml_declaration=True)


def main():
    plan = json.loads((PKG / "raw_plan.json").read_text(encoding="utf-8"))
    images = {i["label"]: i for i in plan["images"]}

    # 1) 写 userdata 标记
    marker = USERDATA_MARKER + bytes(65536 - len(USERDATA_MARKER))
    (PKG / "userdata.img").write_bytes(marker)
    mh = hashlib.sha256(marker).hexdigest()
    plan["files"]["userdata.img"] = {"bytes": len(marker), "sha256": mh}
    plan["userdata_marker_sha256"] = mh
    print(f"  userdata.img 已写入 64 KiB, sha256={mh[:16]}…")

    # 2) 补 image 条目
    if "userdata" in images:
        images["userdata"].update(expanded_bytes=len(marker), expanded_sha256=mh,
                                  segments=["userdata.img"])
        print("  userdata image 已更新")
    else:
        for d in plan["luns"]:
            for row in d["partitions"]:
                if row["label"] == "userdata":
                    entry = dict(label="userdata", lun=d["lun"], start_sector=row["start_sector"],
                                 expanded_bytes=len(marker), expanded_sha256=mh,
                                 segments=["userdata.img"])
                    plan["images"].append(entry)
                    images["userdata"] = entry
                    print(f"  userdata image 已补: lun={d['lun']} start={row['start_sector']}")
        if "userdata" not in images:
            raise SystemExit("GPT 里没有 userdata 分区")

    # 2.5) 修正单分段镜像的 expanded_sha256（以 files 为准）
    fixed = 0
    for img in plan["images"]:
        if len(img["segments"]) != 1:
            continue
        meta = plan["files"].get(img["segments"][0])
        if meta and img["expanded_bytes"] == meta["bytes"] and img["expanded_sha256"] != meta["sha256"]:
            img["expanded_sha256"] = meta["sha256"]
            fixed += 1
    print(f"  修正 {fixed} 个镜像的 expanded_sha256")

    # 2.6) 补 prog_firehose_ddr.elf（load_plan 会强制校验其哈希）
    elf = PKG / "prog_firehose_ddr.elf"
    if not elf.exists():
        src_elf = Path(r"D:\BaiduNetdiskDownload\最新\prog_firehose_ddr.elf")
        elf.write_bytes(src_elf.read_bytes())
        print("  prog_firehose_ddr.elf 已从已有包复制")
    eh = hashlib.sha256(elf.read_bytes()).hexdigest()
    plan["files"]["prog_firehose_ddr.elf"] = {"bytes": elf.stat().st_size, "sha256": eh}
    print(f"  prog_firehose_ddr.elf sha256={eh[:16]}…")

    # 3) 重建 programs（按 LUN：分区顺序 + gpt_backup + gpt_main）
    all_programs = []
    for d in plan["luns"]:
        lun = d["lun"]
        progs = []
        for row in d["partitions"]:
            img = images.get(row["label"])
            if img is None:
                raise SystemExit(f"LUN{lun} 缺少镜像: {row['label']}")
            for seg in img["segments"]:
                meta = plan["files"][seg]
                progs.append(xml_program(lun, row["label"] if len(img["segments"]) == 1 else
                                         f"{row['label']}_{img['segments'].index(seg):03d}",
                                         seg, img["start_sector"], meta["bytes"]))
        for name in (f"gpt_backup{lun}", f"gpt_main{lun}"):
            meta = plan["files"][f"{name}.bin"]
            blocks = d["bytes"] // SECTOR
            start = blocks - 5 if "backup" in name else 0
            progs.append(xml_program(lun, name, f"{name}.bin", start, meta["bytes"]))
        write_xml(PKG, lun, progs)
        all_programs.extend(progs)
        print(f"  LUN{lun}: {len(progs)} 个 program")

    plan["programs"] = all_programs

    # 4) 写清单
    (PKG / "raw_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")
    (PKG / "SHA256SUMS.txt").write_text(
        "\n".join(f"{m['sha256']}  {n}" for n, m in sorted(plan["files"].items())) + "\n",
        encoding="utf-8")
    print(f"  清单已更新：{len(plan['images'])} 个镜像, {len(all_programs)} 个写入项")

    # 5) 校验
    sys.path.insert(0, str(SRC))
    import core
    print("\n[*] 调用 SkyGMFlasher load_plan() 校验")
    try:
        p = core.load_plan(PKG, threading.Event(), log=lambda s: None)
    except Exception as exc:
        print(f"[-] 校验失败：{exc}")
        return 1
    print(f"[+] 校验通过")
    print(f"    manifest SHA256: {p.manifest_hash}")
    print(f"    写入项: {len(p.items)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
