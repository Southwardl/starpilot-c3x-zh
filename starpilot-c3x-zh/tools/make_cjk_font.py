#!/usr/bin/env python3
"""生成 BMFont (.fnt + .png) CJK 字体图集 —— GB2312 全表版。

为什么需要全表：
  地图道路名（如「盘古路」「深圳」）来自运行时地图数据，
  无法从 .po 翻译文件或代码字符串字面量里事先收集。
  只收集 .po/字面量的做法会让「古」「圳」这类字显示成 `?`。

字符集 = ASCII + 特殊符号 + 旧图集已有字符 + GB2312 全部汉字（6763）

用法：
  sudo python3 tools/make_cjk_font.py            # 生成并覆盖设备上的图集
  python3 tools/make_cjk_font.py --out DIR       # 输出到指定目录

依赖：Pillow；源字体 /usr/share/fonts/NotoSansSC-Regular.otf
"""
import argparse
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

DEFAULT_FONT_DIR = Path("/data/openpilot/selfdrive/assets/fonts")
SRC_FONT = Path("/usr/share/fonts/NotoSansSC-Regular.otf")
OUT_STEM = "NotoSansSC-Regular"

FONT_SIZE = 48
PADDING = 6
COLS = 60           # 比旧版 40 更宽，控制图集高度在 8192 以内

EXTRA_CHARS = "–‑✓×°§•⚙✕◀▶✔⌫⇧␣○●↳çêüñ€£¥²⚠ⓘ，。！？、；：“”‘’（）《》【】…—"


def gb2312_chars() -> set[str]:
    """GB2312 全部汉字：一级（16-55 区，常用）+ 二级（56-87 区，地名/生僻字）。"""
    out: set[str] = set()
    for hi in range(0xB0, 0xF8):
        for lo in range(0xA1, 0xFF):
            try:
                out.add(bytes([hi, lo]).decode("gb2312"))
            except UnicodeDecodeError:
                continue
    return out


def existing_atlas_chars(fnt: Path) -> set[str]:
    if not fnt.exists():
        return set()
    t = fnt.read_text(encoding="utf-8", errors="ignore")
    return {chr(int(m)) for m in re.findall(r"char id=(\d+)", t)}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default=None, help="输出目录（默认设备字体目录）")
    args = ap.parse_args()
    out_dir = Path(args.out) if args.out else DEFAULT_FONT_DIR

    if not SRC_FONT.exists():
        print(f"  ❌ 找不到源字体: {SRC_FONT}")
        return 1

    old_fnt = out_dir / f"{OUT_STEM}.fnt"
    chars = set(map(chr, range(32, 127)))
    chars |= set(EXTRA_CHARS)
    chars |= existing_atlas_chars(old_fnt)
    n_old = len(chars)
    gb = gb2312_chars()
    chars |= gb
    print(f"  基础字符(ASCII+符号+旧图集): {n_old}")
    print(f"  GB2312 汉字: {len(gb)}（新增 {len(chars) - n_old}）")

    chars = sorted(c for c in chars if ord(c) >= 32 and c not in "\r\n")
    n = len(chars)
    rows = (n + COLS - 1) // COLS
    cell = FONT_SIZE + PADDING
    atlas_w, atlas_h = COLS * cell, rows * cell
    print(f"  字符总数: {n}")
    print(f"  图集尺寸: {atlas_w}x{atlas_h}")
    if atlas_w > 8192 or atlas_h > 8192:
        print("  ❌ 超过 GPU 8192 限制，需调整 COLS/FONT_SIZE")
        return 1

    font = ImageFont.truetype(str(SRC_FONT), FONT_SIZE)
    ascent, descent = font.getmetrics()

    cover = Image.new("L", (atlas_w, atlas_h), 0)
    draw = ImageDraw.Draw(cover)
    entries = []
    for idx, ch in enumerate(chars):
        col, row = idx % COLS, idx // COLS
        x0, y0, x1, y1 = font.getbbox(ch)
        w, h = x1 - x0, y1 - y0
        advance = int(round(font.getlength(ch)))
        if w > 0 and h > 0:
            draw.text((col * cell - x0, row * cell - y0), ch, font=font, fill=255)
        entries.append({"id": ord(ch), "x": col * cell, "y": row * cell,
                        "width": max(w, 0), "height": max(h, 0),
                        "xoffset": x0, "yoffset": y0, "xadvance": advance})

    out_dir.mkdir(parents=True, exist_ok=True)
    png_path = out_dir / f"{OUT_STEM}.png"
    Image.merge("LA", (Image.new("L", (atlas_w, atlas_h), 255), cover)).save(png_path, optimize=True)

    lines = [
        f'info face="{OUT_STEM}" size=-{FONT_SIZE} bold=0 italic=0 charset="" unicode=1 stretchH=100 smooth=0 aa=1 padding=0,0,0,0 spacing=0,0 outline=0',
        f"common lineHeight={ascent + descent} base={ascent} scaleW={atlas_w} scaleH={atlas_h} pages=1 packed=0 alphaChnl=0 redChnl=4 greenChnl=4 blueChnl=4",
        f'page id=0 file="{OUT_STEM}.png"',
        f"chars count={len(entries)}",
    ]
    for e in entries:
        lines.append(
            "char id={id:<4} x={x:<5} y={y:<5} width={width:<5} height={height:<5} "
            "xoffset={xoffset:<5} yoffset={yoffset:<5} xadvance={xadvance:<5} page=0  chnl=15".format(**e))
    fnt_path = out_dir / f"{OUT_STEM}.fnt"
    fnt_path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    print(f"  fnt: {fnt_path.stat().st_size / 1024:.0f} KB")
    print(f"  png: {png_path.stat().st_size / 1024:.0f} KB")

    ids = {e["id"] for e in entries}
    missing = [ch for ch in "盘古路深圳威朗汽车毫米波雷达" if ord(ch) not in ids]
    print(f"\n  关键字符: {'全部 OK' if not missing else '缺 ' + ''.join(missing)}")
    return 0 if not missing else 1


if __name__ == "__main__":
    sys.exit(main())
