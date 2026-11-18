#!/usr/bin/env python3
"""从 9008 模式的 comma C3X 导出一个符合 SkyGMFlasher 规范的完整刷机包。

依赖 SkyGMFlasher 的源码目录（GPL-3.0-or-later）：protocol.py / package_verify.py /
gpt_normalize.py / serial_transport.py。脚本本身也按 GPL-3.0-or-later 分发。

用法示例：
  # 1) 先探测（只读 GPT，不导出大文件，约 30 秒）
  python build_package.py --port COM10 --out D:\\pkg --dry-run

  # 2) 正式导出
  python build_package.py --port COM10 --out D:\\pkg \\
      --flasher-source "D:\\...\\SkyGMFlasher\\source" \\
      --firehose-from "D:\\BaiduNetdiskDownload\\最新"

  # 3) 校验生成的包
  python build_package.py --verify-only --out D:\\pkg --flasher-source ...

设备必须已进入 9008（05c6:9008）。本脚本只做 READ，不写入任何分区。
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from pathlib import Path

SECTOR = 4096
CHUNK_SECTORS = 256             # 每次读 1 MiB
READ_TIMEOUT = 180              # 单块读取超时（秒）
GPT_MAIN_BYTES = 24576          # 6 扇区
GPT_BACKUP_BYTES = 20480        # 5 扇区
USERDATA_MARKER = b"COMMA_RESET"
CLASSIFICATION = "PRIVATE_FULL_DEVICE_RECOVERY_NOT_PUBLIC_DISTRIBUTION"

# 纯日志/缓存分区，默认写全零（大幅减小包体积，且不影响启动）
DEFAULT_ZERO = ("logdump", "rawdump")

# 身份/校准分区，会在打包时明确警告
IDENTITY_PARTITIONS = (
    "persist", "modemst1", "modemst2", "fsg", "devinfo",
    "keystore", "storsec_a", "storsec_b", "cmnlib_a", "cmnlib_b",
    "cmnlib64_a", "cmnlib64_b", "keymaster_a", "keymaster_b", "frp",
)


def human(n: float) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if abs(n) < 1024 or unit == "TiB":
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} TiB"


def log(msg: str) -> None:
    print(msg, flush=True)


def sha256_file(path: Path, progress=None) -> str:
    h = hashlib.sha256()
    done = 0
    with path.open("rb") as f:
        while data := f.read(8 * 1024 * 1024):
            h.update(data)
            done += len(data)
            if progress:
                progress(done)
    return h.hexdigest()


# ---------------------------------------------------------------- 模块加载

def load_verify_modules(flasher_source: Path):
    """校验只需要 protocol/core/package_verify/gpt_normalize —— 不需要 pyserial。"""
    if not flasher_source.is_dir():
        raise SystemExit(f"找不到 SkyGMFlasher 源码目录：{flasher_source}")
    if str(flasher_source) not in sys.path:
        sys.path.insert(0, str(flasher_source))
    try:
        import protocol
        import package_verify
        import gpt_normalize
    except ImportError as exc:
        raise SystemExit(f"无法导入 SkyGMFlasher 校验模块（{exc}）") from exc
    return protocol, package_verify, gpt_normalize


def load_flasher(flasher_source: Path):
    """设备操作还需要 serial_transport（依赖 pyserial）。"""
    protocol, package_verify, gpt_normalize = load_verify_modules(flasher_source)
    try:
        import serial_transport
    except ImportError as exc:
        raise SystemExit(
            f"无法导入 serial_transport（{exc}）。\n"
            f"设备操作需要 pyserial：python -m pip install pyserial"
        ) from exc
    return serial_transport, protocol, package_verify, gpt_normalize


# ---------------------------------------------------------------- 设备连接

def connect(port: str, firehose_elf: bytes, protocol, serial_transport, retries: int = 3):
    last_exc = None
    for attempt in range(1, retries + 1):
        log(f"[*] 打开 {port}（第 {attempt}/{retries} 次尝试）")
        ser = None
        try:
            ser = serial_transport.open_edl_serial(port)
            fh = protocol.Firehose(protocol.Wire(ser), log)
            log("[*] Sahara 握手 + 加载 Firehose 到 RAM（不写存储）")
            fh.load(firehose_elf)
            log("[*] Firehose configure（UFS）")
            fh.configure()
            log(f"[+] 已连接，设备校验码 {fh.identity}")
            return ser, fh
        except protocol.ProtocolError as exc:
            last_exc = exc
            try:
                if ser:
                    ser.close()
            except Exception:
                pass
            if attempt < retries:
                log(f"[!] 握手失败（{exc}），{5} 秒后重试……")
                time.sleep(5)
                continue
            break

    raise SystemExit(
        f"设备没有响应 Sahara 握手（{last_exc}）。\n"
        "\n"
        "最常见原因：上一次会话已经加载过 Firehose，端口停在 Firehose 状态，\n"
        "必须让设备重新进入 9008 才会重新出现 Sahara HELLO。\n"
        "\n"
        "处理方法（任选其一）：\n"
        "  1. 拔掉 USB 线，等 3 秒再插回        ← 最可靠\n"
        "  2. 长按设备电源键 10 秒断电，再上电\n"
        "  3. 若设备能开机：sudo sh -c 'echo 1 > /sys/module/msm_poweroff/parameters/download_mode' && sudo reboot\n"
        "\n"
        "确认重新出现 05c6:9008 后再运行本脚本。"
    )


def read_lun_geometry(fh, protocol, package_verify, gpt_normalize, lun: int,
                      gpt_dir: Path | None):
    """返回 (total_bytes, blocks, rows, gpt_main_bytes, gpt_backup_bytes)。"""
    import json as _json

    r, logs = fh.command("getstorageinfo", {"physical_partition_number": lun})
    storage = None
    for line in logs:
        if '"storage_info"' in line:
            try:
                storage = _json.loads(line[line.find("{"):])["storage_info"]
            except (ValueError, KeyError):
                continue
    if not isinstance(storage, dict) or not storage:
        raise SystemExit(f"LUN{lun} 没有可验证的 storage_info，停止")

    def integer(name):
        value = storage.get(name)
        if isinstance(value, bool) or not isinstance(value, (int, str)):
            raise SystemExit(f"LUN{lun} storage_info.{name} 无效：{value!r}")
        return int(value, 16) if isinstance(value, str) and value.lower().startswith("0x") else int(value)

    blocks = integer("total_blocks")
    block_size = integer("block_size")
    page_size = integer("page_size")
    kind = str(storage.get("mem_type", "")).strip().upper()
    if kind != "UFS":
        raise SystemExit(f"LUN{lun} 存储类型 {kind!r} 不支持，要求 UFS")
    if block_size != SECTOR or page_size != SECTOR:
        raise SystemExit(f"LUN{lun} 扇区不是 4096（block={block_size} page={page_size}）")

    main = fh.read(lun, 0, 6)
    backup = fh.read(lun, blocks - 5, 5)
    if len(main) != GPT_MAIN_BYTES or len(backup) != GPT_BACKUP_BYTES:
        raise SystemExit(f"LUN{lun} GPT 长度异常")

    # 读路径：优先使用设备原始 GPT，只在自相矛盾时做最小修复。
    # 注意 fix_degenerate_lun0 是「写包”用的单槽布局修复，读设备时通常不适用。
    rows = None
    try:
        rows = package_verify.gpt_pair(main, backup, blocks)
    except AssertionError:
        # 1) 备份 GPT 头 CRC 过期（常见）
        try:
            nu_backup, changed = gpt_normalize.normalize_backup_crc(main, backup, blocks)
            rows = package_verify.gpt_pair(main, nu_backup, blocks)
            backup = nu_backup
            log(f"    LUN{lun}: 备份 GPT 头 CRC 已归一化{'（已修改）' if changed else ''}")
        except AssertionError:
            # 2) 单槽退化布局
            try:
                fm, fb, _ = gpt_normalize.fix_degenerate_lun0(main, backup, blocks)
                fb, _ = gpt_normalize.normalize_backup_crc(fm, fb, blocks)
                rows = package_verify.gpt_pair(fm, fb, blocks)
                main, backup = fm, fb
                log(f"    LUN{lun}: 退化 GPT 经最小修复后解析成功")
            except AssertionError as exc:
                raise SystemExit(
                    f"LUN{lun} GPT 无法解析（{exc}）。\n"
                    f"请用 SkyGMFlasher 的「一键启动诊断备份」保存原始 GPT 后分析。")
    if rows is None:
        raise SystemExit(f"LUN{lun} GPT 解析失败")

    if gpt_dir is not None:
        gpt_dir.mkdir(parents=True, exist_ok=True)
        (gpt_dir / f"gpt_main{lun}.bin").write_bytes(main)
        (gpt_dir / f"gpt_backup{lun}.bin").write_bytes(backup)

    total = blocks * SECTOR
    log(f"    LUN{lun}: {human(total)} · {len(rows)} 个分区 · type={kind}")
    return total, blocks, rows, main, backup


# ---------------------------------------------------------------- 导出分区

def read_sectors(fh, lun: int, sector: int, count: int, attempts: int = 1):
    """分块读取。

    ⚠ EDL 的 read 超时后设备可能仍在发送，残留字节会让下一次命令解析失败（协议错位），
    所以默认**不重试**：宁可整盘失败重启会话，也不要在错位的流上继续。
    """
    last = None
    for i in range(attempts):
        try:
            return firehose_read(fh, lun, sector, count)
        except Exception as exc:
            last = exc
            if i + 1 < attempts:
                log(f"      ⚠ 读 LUN{lun} sector={sector} count={count} 失败（{exc}），重试 {i+2}/{attempts}")
                time.sleep(1)
    raise SystemExit(f"读取 LUN{lun} sector={sector} count={count} 失败：{last}")


def firehose_read(fh, lun: int, start: int, count: int, timeout: float | None = None):
    """与 protocol.Firehose.read 相同，但可指定更长的超时。

    原实现的 60 秒超时在慢速/抖动链路上不够用，会让整个分区读取失败。
    """
    t = READ_TIMEOUT if timeout is None else timeout
    r, _ = fh.command("read", fh.address(lun, start, count))
    fh.rawmode(r, True)
    data = fh.wire.exact(count * SECTOR, timeout=t)
    r, _ = fh.response()
    fh.rawmode(r, False)
    return data


def dump_partition(fh, protocol, lun: int, label: str, start_sector: int, size: int,
                   out_dir: Path, split_bytes: int | None, zero: bool,
                   progress_cb=None):
    """读取一个分区，返回 (segments, expanded_sha256, expanded_bytes)。

    零填充模式下不读设备，直接写零（用于 logdump 等日志分区）。
    """
    h = hashlib.sha256()
    segments: list[str] = []
    if zero:
        log(f"      零填充 {label} ({human(size)})")
        block = bytes(8 * 1024 * 1024)
        remaining = size
        idx = 0
        while remaining > 0:
            part = min(remaining, split_bytes) if split_bytes else remaining
            if not split_bytes or size <= split_bytes:
                name = f"{label}.img"
            else:
                name = f"{label}_{idx:03d}.img"
            with (out_dir / name).open("wb") as f:
                left = part
                while left > 0:
                    n = min(len(block), left)
                    f.write(block[:n])
                    h.update(block[:n])
                    left -= n
            segments.append(name)
            remaining -= part
            idx += 1
        return segments, h.hexdigest(), size

    remaining = size
    idx = 0
    done = 0
    while remaining > 0:
        part = min(remaining, split_bytes) if split_bytes else remaining
        if not split_bytes or size <= split_bytes:
            name = f"{label}.img"
        else:
            name = f"{label}_{idx:03d}.img"
        with (out_dir / name).open("wb") as f:
            left = part
            sector = start_sector + (size - remaining) // SECTOR
            while left > 0:
                count = min(CHUNK_SECTORS, left // SECTOR)
                if count <= 0:
                    raise SystemExit(f"{label} 尾部不足一个扇区")
                data = read_sectors(fh, lun, sector, count)
                f.write(data)
                h.update(data)
                sector += count
                left -= count * SECTOR
                done += count * SECTOR
                if progress_cb:
                    progress_cb(done, size)
        segments.append(name)
        remaining -= part
        idx += 1
    return segments, h.hexdigest(), size


# ---------------------------------------------------------------- 写包

def write_xml(out_dir: Path, lun: int, programs: list[dict], ) -> None:
    root = ET.Element("data")
    for a in programs:
        ET.SubElement(root, "program", {k: str(v) for k, v in a.items()})
    ET.ElementTree(root).write(out_dir / f"rawprogram{lun}.xml",
                               encoding="utf-8", xml_declaration=True)
    patches = ET.Element("patches")
    ET.ElementTree(patches).write(out_dir / f"patch{lun}.xml",
                                  encoding="utf-8", xml_declaration=True)


def xml_program(lun: int, label: str, filename: str, start_sector: int, size: int) -> dict:
    # 所有值必须是字符串：verify_raw 会用 dict(xml_attrib) 与本清单直接比较
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


def verify_package(out_dir: Path, flasher_source: Path) -> bool:
    load_verify_modules(flasher_source)
    import core
    import threading
    log(f"[*] 用 SkyGMFlasher 自身的 load_plan() 校验 {out_dir}")
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


# ---------------------------------------------------------------- main

def main() -> int:
    ap = argparse.ArgumentParser(
        description="从 9008 设备导出 SkyGMFlasher 兼容的完整刷机包（只读，不写设备）")
    ap.add_argument("--port", help="9008 串口，如 COM10")
    ap.add_argument("--out", required=True, help="输出包目录（必须为空或不存在）")
    ap.add_argument("--flasher-source", help="SkyGMFlasher\\source 目录")
    ap.add_argument("--firehose-from", help="从中复制 prog_firehose_ddr.elf 的现有包目录")
    ap.add_argument("--split-mb", type=int, default=1024,
                    help="超过此大小的分区按此大小切分（默认 1024 MB，0=不切分）")
    ap.add_argument("--zero", default=",".join(DEFAULT_ZERO),
                    help=f"写全零的分区（默认 {','.join(DEFAULT_ZERO)}）")
    ap.add_argument("--dump", default="", help="只导出这些分区（逗号分隔，默认全部）")
    ap.add_argument("--skip", default="userdata",
                    help="跳过的分区（默认 userdata，会自动写入 64 KiB 复位标记）")
    ap.add_argument("--dry-run", action="store_true", help="只读 GPT 并打印计划，不导出")
    ap.add_argument("--verify-only", action="store_true", help="只校验 --out 目录")
    ap.add_argument("--yes", action="store_true", help="跳过确认提示")
    ap.add_argument("--no-reset", action="store_true", help="结束后不重启设备（默认会 power reset）")
    args = ap.parse_args()

    out_dir = Path(args.out).expanduser().resolve()
    flasher_source = Path(args.flasher_source).expanduser().resolve() if args.flasher_source else None

    # ---- 校验模式 ----
    if args.verify_only:
        if flasher_source is None:
            raise SystemExit("--verify-only 需要 --flasher-source")
        return 0 if verify_package(out_dir, flasher_source) else 1

    if not args.port:
        raise SystemExit("需要 --port")
    if flasher_source is None:
        raise SystemExit("需要 --flasher-source")

    serial_transport, protocol, package_verify, gpt_normalize = load_flasher(flasher_source)

    # ---- Firehose 引导 ----
    if args.firehose_from:
        elf_path = Path(args.firehose_from).expanduser().resolve() / "prog_firehose_ddr.elf"
        if not elf_path.is_file():
            raise SystemExit(f"找不到 {elf_path}")
        elf = elf_path.read_bytes()
        digest = hashlib.sha256(elf).hexdigest()
        if digest != protocol.LOADER_SHA256:
            raise SystemExit(
                f"Firehose 哈希与工具登记值不符，禁止使用\n"
                f"  实际 {digest}\n  要求 {protocol.LOADER_SHA256}")
        log(f"[+] Firehose 引导哈希匹配：{digest[:16]}…")
    else:
        raise SystemExit("需要 --firehose-from（提供已登记的 prog_firehose_ddr.elf）")

    zero_set = {s.strip() for s in args.zero.split(",") if s.strip()}
    dump_set = {s.strip() for s in args.dump.split(",") if s.strip()}
    skip_set = {s.strip() for s in args.skip.split(",") if s.strip()}
    split_bytes = args.split_mb * 1024 * 1024 if args.split_mb else None

    # 输出目录必须在连接前就确定好（读几何时就会写入 GPT 文件）
    if not args.dry_run:
        if out_dir.exists() and any(out_dir.iterdir()):
            raise SystemExit(f"输出目录非空，请先清空或换一个：{out_dir}")
        out_dir.mkdir(parents=True, exist_ok=True)

    # ---- 连接 ----
    ser, fh = connect(args.port, elf, protocol, serial_transport)
    try:
        # ---- 读布局 ----
        log("[*] 读取 6 个 LUN 的容量与主/备 GPT")
        gpt_dir = None if args.dry_run else out_dir
        luns = []
        for lun in range(6):
            total, blocks, rows, _, _ = read_lun_geometry(
                fh, protocol, package_verify, gpt_normalize, lun, gpt_dir)
            luns.append(dict(lun=lun, bytes=total, sector_size=SECTOR,
                             partitions=rows, blocks=blocks))

        # ---- 构建写入清单 ----
        items = []          # (lun, label, start_sector, size, zero?)
        total_bytes = 0
        for d in luns:
            lun, blocks = d["lun"], d["blocks"]
            for row in d["partitions"]:
                label, start, size = row["label"], row["start_sector"], row["bytes"]
                if label in skip_set:
                    continue
                if dump_set and label not in dump_set:
                    continue
                items.append((lun, label, start, size, label in zero_set))
                total_bytes += size
            # GPT 项必写（工具硬性要求最后写入）
            items.append((lun, f"gpt_main{lun}", 0, GPT_MAIN_BYTES, False))
            items.append((lun, f"gpt_backup{lun}", blocks - 5, GPT_BACKUP_BYTES, False))
            total_bytes += GPT_MAIN_BYTES + GPT_BACKUP_BYTES

        # userdata：写 64 KiB 复位标记（让首启自动重建）
        userdata_row = None
        for d in luns:
            for row in d["partitions"]:
                if row["label"] == "userdata":
                    userdata_row = (d["lun"], row)

        log("")
        log("=" * 72)
        log(f"计划导出 {len(items)} 项 · 合计 {human(total_bytes)}")
        log(f"  切分阈值: {'不切分' if split_bytes is None else human(split_bytes)}")
        log(f"  零填充  : {', '.join(sorted(zero_set & {i[1] for i in items})) or '无'}")
        log(f"  跳过    : {', '.join(sorted(skip_set)) or '无'}")
        if userdata_row:
            log(f"  userdata: 将写入 64 KiB 复位标记（不导出原用户区）")
        log("=" * 72)

        if args.dry_run:
            log("")
            log("[dry-run] 各 LUN 分区明细：")
            for d in luns:
                log(f"  LUN{d['lun']}  {human(d['bytes'])}")
                for row in d["partitions"]:
                    mark = " [零]" if row["label"] in zero_set else ""
                    mark += " [跳过]" if row["label"] in skip_set else ""
                    log(f"      {row['label']:<22} start={row['start_sector']:<10} {human(row['bytes']):>10}{mark}")
            log("")
            log("[dry-run] 未导出任何数据，设备未被写入。")
            return 0

        warn = [i[1] for i in items if i[1] in IDENTITY_PARTITIONS]
        if warn:
            log("")
            log("⚠ 以下身份/校准分区将被打包（刷到别的设备会覆盖对方的硬件身份）：")
            for name in warn:
                log(f"    {name}")
            log("  如果只是给其他设备装软件，不要用这个包；直接跑 install.sh 即可。")
        if not args.yes:
            ans = input("\n确认导出？输入 yes 继续：").strip().lower()
            if ans != "yes":
                log("已取消。")
                return 1

        # ---- 导出 ----

        files_meta: dict[str, dict] = {}
        images: list[dict] = []
        programs_by_lun: dict[int, list[dict]] = {i: [] for i in range(6)}

        for n, (lun, label, start, size, zero) in enumerate(items, 1):
            log(f"[{n}/{len(items)}] {label} ({human(size)}){' 零填充' if zero else ''}")
            if label.startswith("gpt_"):
                name = f"{label}.bin"
                src = out_dir / name
                if not src.exists():
                    raise SystemExit(f"缺少 GPT 文件 {src}")
                digest = sha256_file(src)
                files_meta[name] = {"bytes": src.stat().st_size, "sha256": digest}
                segments = [name]
                expanded = src.stat().st_size
            elif label == "userdata":
                name = "userdata.img"
                marker = USERDATA_MARKER + bytes(65536 - len(USERDATA_MARKER))
                (out_dir / name).write_bytes(marker)
                digest = hashlib.sha256(marker).hexdigest()
                files_meta[name] = {"bytes": len(marker), "sha256": digest}
                segments = [name]
                expanded = len(marker)
            else:
                last = [0.0]

                def cb(done, total, _l=label):
                    now = time.time()
                    if now - last[0] > 3 or done >= total:
                        last[0] = now
                        log(f"      {done * 100 // max(total, 1):3d}%  {human(done)} / {human(total)}")

                segments, digest, expanded = dump_partition(
                    fh, protocol, lun, label, start, size, out_dir,
                    split_bytes, zero, cb)
                for seg in segments:
                    p = out_dir / seg
                    files_meta[seg] = {"bytes": p.stat().st_size, "sha256": sha256_file(p)}

            for seg in segments:
                programs_by_lun[lun].append(
                    xml_program(lun, label if len(segments) == 1 else f"{label}:{seg}",
                                seg, start if seg == segments[0] else 0, files_meta[seg]["bytes"]))
            # 修正连续分段起始扇区（全部保持字符串，与 XML 属性一致）
            if len(segments) > 1:
                off = 0
                for idx, seg in enumerate(segments):
                    entry = programs_by_lun[lun][-len(segments) + idx]
                    sector = start + off // SECTOR
                    entry["start_sector"] = str(sector)
                    entry["start_byte_hex"] = hex(sector * SECTOR)
                    entry["num_partition_sectors"] = str(files_meta[seg]["bytes"] // SECTOR)
                    entry["size_in_KB"] = f"{files_meta[seg]['bytes'] / 1024:.1f}"
                    entry["label"] = f"{label}_{idx:03d}"
                    off += files_meta[seg]["bytes"]

            images.append(dict(label=label, lun=lun, start_sector=start,
                               expanded_bytes=expanded, expanded_sha256=digest,
                               segments=segments))

        # GPT 必须最后写入
        for lun in range(6):
            progs = programs_by_lun[lun]
            main = [p for p in progs if p["label"] == f"gpt_main{lun}"]
            back = [p for p in progs if p["label"] == f"gpt_backup{lun}"]
            progs[:] = [p for p in progs if p not in main + back] + back + main
            write_xml(out_dir, lun, progs)

        all_programs = [p for lun in range(6) for p in programs_by_lun[lun]]

        # ---- 清单 ----
        plan = {
            "version": f"CUSTOM-FULL-9008-{time.strftime('%Y%m%d')}",
            "classification": CLASSIFICATION,
            "status": "CUSTOM_BUILT_FROM_DEVICE_NOT_DEVICE_WRITE_TESTED",
            "sector_size": SECTOR,
            "storage": "ext4 (stock AGNOS, plain userdata)",
            "userdata_marker_sha256": hashlib.sha256(
                USERDATA_MARKER + bytes(65536 - len(USERDATA_MARKER))).hexdigest(),
            "source_device": dict(identity=str(fh.identity), built_at=time.strftime("%Y-%m-%dT%H:%M:%S%z")),
            "luns": [dict(lun=d["lun"], bytes=d["bytes"], sector_size=SECTOR,
                          partitions=d["partitions"]) for d in luns],
            "images": images,
            "programs": all_programs,
            "files": files_meta,
        }
        (out_dir / "raw_plan.json").write_text(
            json.dumps(plan, ensure_ascii=False, indent=1), encoding="utf-8")

        lines = [f"{meta['sha256']}  {name}" for name, meta in sorted(files_meta.items())]
        (out_dir / "SHA256SUMS.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
        (out_dir / "README.txt").write_text(
            f"自建设备包 / {time.strftime('%Y-%m-%d')}\n\n"
            f"由 build_package.py 从实机 9008 只读导出生成。\n"
            f"分类标记沿用工具要求的 {CLASSIFICATION}。\n\n"
            f"【重要】\n"
            f"- 包含来源设备的 persist/modemst/fsg/devinfo 等身份与校准数据。\n"
            f"- 刷到其他设备会覆盖对方的硬件身份，仅用于整机克隆或恢复。\n"
            f"- userdata 只写 64 KiB 复位标记，首启由 AGNOS 自动重建（rm -rf 后 mkfs）。\n"
            f"- 未经实机刷写验证，请先在可放弃的测试机上试。\n",
            encoding="utf-8")

        log("")
        log(f"[+] 包已生成：{out_dir}")
        log(f"    文件 {len(files_meta)} 个 · 合计 {human(sum(m['bytes'] for m in files_meta.values()))}")
    finally:
        if not args.no_reset:
            try:
                log("[*] 发送 power reset，让设备正常重启（本次未写入任何分区）")
                fh.reset()
                time.sleep(2)
            except Exception as exc:
                log(f"[!] reset 失败（{exc}）—— 请手动断电重启，否则设备会停在 Firehose")
        try:
            ser.close()
        except Exception:
            pass

    # ---- 自校验 ----
    log("")
    return 0 if verify_package(out_dir, flasher_source) else 1


if __name__ == "__main__":
    sys.exit(main())
