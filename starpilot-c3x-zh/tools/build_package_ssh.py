#!/usr/bin/env python3
"""通过 SSH 从「正常开机」的 comma 设备导出 SkyGMFlasher 兼容的刷机包。

相比 EDL/Firehose 读取，这条路径：
  * 不依赖 9008，设备正常开机即可
  * 走标准块设备（dd），无协议层，不会错位
  * 单个分区失败可单独重来
  * 速度取决于网络（WiFi 一般 8-15 MB/s）

依赖 SkyGMFlasher 的源码目录（GPL-3.0-or-later）用于 GPT 解析与最终自校验。

用法：
  # 探测（只读 GPT）
  python build_package_ssh.py --ssh comma@192.168.1.12 --out D:\\c3x_pkg --dry-run

  # 正式导出
  python build_package_ssh.py --ssh comma@192.168.1.12 --out D:\\c3x_pkg \
      --flasher-source "D:\\...\\SkyGMFlasher\\source" \
      --firehose-from "D:\\BaiduNetdiskDownload\\最新"

  # 只校验
  python build_package_ssh.py --verify-only --out D:\\c3x_pkg --flasher-source ...
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

SECTOR = 4096
GPT_MAIN_BYTES = 24576
GPT_BACKUP_BYTES = 20480
USERDATA_MARKER = b"COMMA_RESET"
CLASSIFICATION = "PRIVATE_FULL_DEVICE_RECOVERY_NOT_PUBLIC_DISTRIBUTION"
DEFAULT_ZERO = ("logdump", "rawdump")
IDENTITY_PARTITIONS = (
    "persist", "modemst1", "modemst2", "fsg", "devinfo",
    "keystore", "storsec_a", "storsec_b", "cmnlib_a", "cmnlib_b",
    "cmnlib64_a", "cmnlib64_b", "keymaster_a", "keymaster_b", "frp",
)
LUN_COUNT = 6
DEV = ["sda", "sdb", "sdc", "sdd", "sde", "sdf"]


def human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} TiB"


def log(m: str) -> None:
    print(m, flush=True)


def sha256_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as f:
        while d := f.read(8 * 1024 * 1024):
            h.update(d)
    return h.hexdigest()


# ---------------------------------------------------------------- SSH

class SSHRunner:
    def __init__(self, target: str, opts: list[str]):
        self.target = target
        self.opts = opts

    def _cmd(self) -> list[str]:
        return ["ssh", "-o", "BatchMode=yes", "-o", "ConnectTimeout=15",
                "-o", "ServerAliveInterval=15", *self.opts, self.target]

    def run(self, remote: str, timeout: int = 60) -> bytes:
        p = subprocess.run(self._cmd() + [remote], capture_output=True, timeout=timeout)
        if p.returncode != 0:
            raise SystemExit(f"远程命令失败：{remote}\n{p.stderr.decode('utf-8', 'ignore')[:400]}")
        return p.stdout

    def stream(self, remote: str, dest: Path, expect: int, progress=None,
               skip_bytes: int = 0, count_bytes: int | None = None) -> str:
        """把远端 dd 的输出流式写盘并计算 SHA-256。"""
        h = hashlib.sha256()
        done = 0
        last = [0.0]
        parts = ["sudo -n dd", f"if={remote}", "bs=4M"]
        if skip_bytes:
            parts.append(f"skip={skip_bytes // (4 * 1024 * 1024)}")
        if count_bytes is not None and count_bytes % (4 * 1024 * 1024) == 0:
            parts.append(f"count={count_bytes // (4 * 1024 * 1024)}")
        elif count_bytes is not None:
            # 非 4 MiB 整数倍：退回 4 KiB 块，保证精确
            parts = ["sudo -n dd", f"if={remote}", "bs=4096",
                     f"skip={skip_bytes // 4096}", f"count={count_bytes // 4096}"]
        parts.append("status=none")
        cmd = self._cmd() + [" ".join(parts)]
        with dest.open("wb") as f, subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                                    stderr=subprocess.PIPE) as p:
            assert p.stdout is not None
            while True:
                chunk = p.stdout.read(4 * 1024 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                h.update(chunk)
                done += len(chunk)
                if progress:
                    now = time.time()
                    if now - last[0] > 3 or done >= expect:
                        last[0] = now
                        progress(done, expect)
            err = p.stderr.read().decode("utf-8", "ignore") if p.stderr else ""
            p.wait()
        if p.returncode != 0:
            raise SystemExit(f"dd 失败：{remote}\n{err[:400]}")
        if done != expect:
            raise SystemExit(f"长度不符：{remote} 期望 {expect} 实得 {done}")
        return h.hexdigest()


# ---------------------------------------------------------------- 规模

def load_tool(flasher_source: Path):
    if not (flasher_source / "package_verify.py").is_file():
        raise SystemExit(f"--flasher-source 无效：{flasher_source}")
    if str(flasher_source) not in sys.path:
        sys.path.insert(0, str(flasher_source))
    import package_verify
    import gpt_normalize
    return package_verify, gpt_normalize


def verify_package(out_dir: Path, flasher_source: Path) -> bool:
    load_tool(flasher_source)
    import core
    import threading
    log(f"[*] 用 SkyGMFlasher 的 load_plan() 校验 {out_dir}")
    t0 = time.time()
    try:
        plan = core.load_plan(out_dir, threading.Event(), log=lambda s: None)
    except Exception as exc:
        log(f"[-] 校验失败：{exc}")
        return False
    log(f"[+] 校验通过（{time.time() - t0:.0f} 秒）")
    log(f"    manifest SHA256: {plan.manifest_hash}")
    log(f"    写入项: {len(plan.items)}")
    return True


def xml_program(lun: int, label: str, filename: str, start_sector: int, size: int) -> dict:
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
    ET.ElementTree(root).write(out_dir / f"rawprogram{lun}.xml",
                               encoding="utf-8", xml_declaration=True)
    ET.ElementTree(ET.Element("patches")).write(out_dir / f"patch{lun}.xml",
                                                encoding="utf-8", xml_declaration=True)


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(description="通过 SSH/dd 导出 SkyGMFlasher 兼容刷机包")
    ap.add_argument("--ssh", help="SSH 目标，如 comma@192.168.1.12")
    ap.add_argument("--ssh-key", help="SSH 私钥路径（可选）")
    ap.add_argument("--out", required=True)
    ap.add_argument("--flasher-source", help="SkyGMFlasher/source 目录")
    ap.add_argument("--firehose-from", help="从中复制 prog_firehose_ddr.elf 的现有包")
    ap.add_argument("--split-mb", type=int, default=1024)
    ap.add_argument("--zero", default=",".join(DEFAULT_ZERO))
    ap.add_argument("--skip", default="")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--yes", action="store_true")
    args = ap.parse_args()

    out_dir = Path(args.out).expanduser().resolve()

    if args.verify_only:
        if not args.flasher_source:
            raise SystemExit("--verify-only 需要 --flasher-source")
        return 0 if verify_package(out_dir, Path(args.flasher_source).expanduser().resolve()) else 1

    if not args.ssh:
        raise SystemExit("需要 --ssh")
    if not args.flasher_source:
        raise SystemExit("需要 --flasher-source")
    if not args.firehose_from:
        raise SystemExit("需要 --firehose-from（提供已登记的 prog_firehose_ddr.elf）")

    package_verify, gpt_normalize = load_tool(Path(args.flasher_source).expanduser().resolve())

    opts = []
    if args.ssh_key:
        opts += ["-i", str(Path(args.ssh_key).expanduser())]
    ssh = SSHRunner(args.ssh, opts)

    zero_set = {s.strip() for s in args.zero.split(",") if s.strip()}
    skip_set = {s.strip() for s in args.skip.split(",") if s.strip()}
    split_bytes = args.split_mb * 1024 * 1024 if args.split_mb else None

    # Firehose 引导
    elf_src = Path(args.firehose_from).expanduser().resolve() / "prog_firehose_ddr.elf"
    if not elf_src.is_file():
        raise SystemExit(f"找不到 {elf_src}")

    # 目录准备
    if not args.dry_run:
        if out_dir.exists() and any(out_dir.iterdir()):
            raise SystemExit(f"输出目录非空：{out_dir}")
        out_dir.mkdir(parents=True, exist_ok=True)

    # ---- 读几何 ----
    log(f"[*] 连接 {args.ssh}")
    log(ssh.run("echo connected && uname -sr").decode("utf-8", "ignore").strip())

    luns = []
    for lun in range(LUN_COUNT):
        dev = f"/dev/{DEV[lun]}"
        size512 = int(ssh.run(f"cat /sys/class/block/{DEV[lun]}/size").decode().strip())
        blocks = size512 // (SECTOR // 512)          # 4096 字节扇区数
        total = blocks * SECTOR
        tmp_main = f"/tmp/.gpth_{lun}"
        tmp_back = f"/tmp/.gptb_{lun}"
        if args.dry_run:
            main_b = ssh.run(f"sudo -n dd if={dev} bs=4096 count=6 status=none", timeout=60)
            back_b = ssh.run(f"sudo -n dd if={dev} bs=4096 skip={blocks - 5} count=5 status=none", timeout=60)
        else:
            ssh.run(f"sudo -n dd if={dev} bs=4096 count=6 of={tmp_main} status=none")
            ssh.run(f"sudo -n dd if={dev} bs=4096 skip={blocks - 5} count=5 of={tmp_back} status=none")
            main_b = ssh.run(f"sudo -n cat {tmp_main}")
            back_b = ssh.run(f"sudo -n cat {tmp_back}")
            ssh.run(f"sudo -n rm -f {tmp_main} {tmp_back}")
        if len(main_b) != GPT_MAIN_BYTES or len(back_b) != GPT_BACKUP_BYTES:
            raise SystemExit(f"LUN{lun} GPT 长度异常 ({len(main_b)}/{len(back_b)})")
        try:
            rows = package_verify.gpt_pair(main_b, back_b, blocks)
        except AssertionError:
            back_b, _ = gpt_normalize.normalize_backup_crc(main_b, back_b, blocks)
            rows = package_verify.gpt_pair(main_b, back_b, blocks)
            log(f"    LUN{lun}: 备份 GPT 头 CRC 已归一化")
        if not args.dry_run:
            (out_dir / f"gpt_main{lun}.bin").write_bytes(main_b)
            (out_dir / f"gpt_backup{lun}.bin").write_bytes(back_b)
        luns.append(dict(lun=lun, bytes=total, blocks=blocks, partitions=rows))
        log(f"    LUN{lun}: {human(total)} · {len(rows)} 个分区")

    # ---- 清单 ----
    items = []
    total_bytes = 0
    for d in luns:
        for row in d["partitions"]:
            if row["label"] in skip_set:
                continue
            items.append((d["lun"], row["label"], row["start_sector"], row["bytes"],
                          row["label"] in zero_set))
            total_bytes += row["bytes"]
        items.append((d["lun"], f"gpt_main{d['lun']}", 0, GPT_MAIN_BYTES, False))
        items.append((d["lun"], f"gpt_backup{d['lun']}", d["blocks"] - 5, GPT_BACKUP_BYTES, False))
        total_bytes += GPT_MAIN_BYTES + GPT_BACKUP_BYTES

    log("")
    log("=" * 72)
    log(f"计划导出 {len(items)} 项 · 合计 {human(total_bytes)}")
    if args.dry_run:
        for d in luns:
            log(f"  LUN{d['lun']}  {human(d['bytes'])}")
            for row in d["partitions"]:
                mark = " [零]" if row["label"] in zero_set else ""
                mark += " [跳过]" if row["label"] in skip_set else ""
                log(f"      {row['label']:<22} start={row['start_sector']:<10} {human(row['bytes']):>10}{mark}")
        log("")
        log("[dry-run] 未导出数据。")
        return 0
    log("=" * 72)

    warn = [i[1] for i in items if i[1] in IDENTITY_PARTITIONS]
    if warn:
        log("⚠ 以下身份/校准分区将被打包：")
        for n in warn:
            log(f"    {n}")
    if not args.yes:
        if input("\n确认导出？输入 yes 继续：").strip().lower() != "yes":
            log("已取消。")
            return 1

    # ---- 导出 ----
    files_meta: dict[str, dict] = {}
    images: list[dict] = []
    programs_by_lun: dict[int, list[dict]] = {i: [] for i in range(LUN_COUNT)}

    for n, (lun, label, start, size, zero) in enumerate(items, 1):
        log(f"[{n}/{len(items)}] {label} ({human(size)}){' 零填充' if zero else ''}")
        if label.startswith("gpt_"):
            name = f"{label}.bin"
            p = out_dir / name
            digest = sha256_file(p)
            files_meta[name] = {"bytes": p.stat().st_size, "sha256": digest}
            segments, expanded = [name], p.stat().st_size
        elif label == "userdata":
            name = "userdata.img"
            marker = USERDATA_MARKER + bytes(65536 - len(USERDATA_MARKER))
            (out_dir / name).write_bytes(marker)
            files_meta[name] = {"bytes": len(marker), "sha256": hashlib.sha256(marker).hexdigest()}
            segments, expanded = [name], len(marker)
        elif zero:
            name = "".join([f"{label}.img"])
            block = bytes(8 * 1024 * 1024)
            h = hashlib.sha256()
            with (out_dir / name).open("wb") as f:
                left = size
                while left > 0:
                    k = min(len(block), left)
                    f.write(block[:k])
                    h.update(block[:k])
                    left -= k
            files_meta[name] = {"bytes": size, "sha256": h.hexdigest()}
            segments, expanded = [name], size
            digest = h.hexdigest()
        else:
            idx = 0
            segments = []
            h_total = hashlib.sha256()
            remaining = size
            cur = start
            while remaining > 0:
                part = min(remaining, split_bytes) if split_bytes else remaining
                name = f"{label}.img" if (not split_bytes or size <= split_bytes) else f"{label}_{idx:03d}.img"
                last = [0.0]

                def cb(done, tot, _l=label, _s=size):
                    now = time.time()
                    if now - last[0] > 3 or done >= tot:
                        last[0] = now
                        log(f"      {done * 100 // max(tot, 1):3d}%  {human(done)} / {human(tot)}")

                digest = ssh.stream(
                    f"/dev/disk/by-partlabel/{label}", out_dir / name, part, cb,
                    skip_bytes=(size - remaining),
                    count_bytes=(part if split_bytes else None))
                files_meta[name] = {"bytes": part, "sha256": digest}
                with (out_dir / name).open("rb") as f:
                    while d := f.read(8 * 1024 * 1024):
                        h_total.update(d)
                segments.append(name)
                remaining -= part
                cur += part // SECTOR
                idx += 1
            expanded = size
            digest = h_total.hexdigest()

        off = 0
        for i, seg in enumerate(segments):
            lbl = label if len(segments) == 1 else f"{label}_{i:03d}"
            sec = start + off // SECTOR
            programs_by_lun[lun].append(xml_program(lun, lbl, seg, sec, files_meta[seg]["bytes"]))
            off += files_meta[seg]["bytes"]
        images.append(dict(label=label, lun=lun, start_sector=start,
                           expanded_bytes=expanded, expanded_sha256=digest,
                           segments=segments))

    for lun in range(LUN_COUNT):
        progs = programs_by_lun[lun]
        main = [p for p in progs if p["label"] == f"gpt_main{lun}"]
        back = [p for p in progs if p["label"] == f"gpt_backup{lun}"]
        progs[:] = [p for p in progs if p not in main + back] + back + main
        write_xml(out_dir, lun, progs)

    plan = {
        "version": f"CUSTOM-SSH-9008-{time.strftime('%Y%m%d')}",
        "classification": CLASSIFICATION,
        "status": "CUSTOM_BUILT_FROM_DEVICE_SSH_DD_NOT_DEVICE_WRITE_TESTED",
        "sector_size": SECTOR,
        "storage": "ext4 (stock AGNOS, plain userdata)",
        "userdata_marker_sha256": hashlib.sha256(
            USERDATA_MARKER + bytes(65536 - len(USERDATA_MARKER))).hexdigest(),
        "source_device": dict(ssh=args.ssh, built_at=time.strftime("%Y-%m-%dT%H:%M:%S%z")),
        "luns": [dict(lun=d["lun"], bytes=d["bytes"], sector_size=SECTOR,
                      partitions=d["partitions"]) for d in luns],
        "images": images,
        "programs": [p for lun in range(LUN_COUNT) for p in programs_by_lun[lun]],
        "files": files_meta,
    }
    (out_dir / "raw_plan.json").write_text(json.dumps(plan, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    (out_dir / "SHA256SUMS.txt").write_text(
        "\n".join(f"{m['sha256']}  {n}" for n, m in sorted(files_meta.items())) + "\n",
        encoding="utf-8")
    (out_dir / "prog_firehose_ddr.elf").write_bytes(elf_src.read_bytes())
    files_meta["prog_firehose_ddr.elf"] = {
        "bytes": elf_src.stat().st_size,
        "sha256": hashlib.sha256(elf_src.read_bytes()).hexdigest(),
    }
    (out_dir / "README.txt").write_text(
        f"自建设备包（SSH/dd 导出）/ {time.strftime('%Y-%m-%d')}\n\n"
        f"包含来源设备的 persist/modemst/fsg/devinfo 等身份与校准数据。\n"
        f"userdata 只写 64 KiB 复位标记，首启由 AGNOS 自动重建。\n"
        f"未经实机刷写验证。\n", encoding="utf-8")

    log("")
    log(f"[+] 包已生成：{out_dir}")
    log(f"    文件 {len(files_meta)} 个 · {human(sum(m['bytes'] for m in files_meta.values()))}")
    log("")
    return 0 if verify_package(out_dir, Path(args.flasher_source).expanduser().resolve()) else 1


if __name__ == "__main__":
    sys.exit(main())
