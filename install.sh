#!/usr/bin/env bash
# StarPilot C3X 汉化 + 定制补丁 安装器
# 用法: sudo bash install.sh [--force] [--no-restart]
set -uo pipefail

OPENPILOT="${OPENPILOT_DIR:-/data/openpilot}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FORCE=0
NO_RESTART=0
for arg in "$@"; do
  case "$arg" in
    --force) FORCE=1 ;;
    --no-restart) NO_RESTART=1 ;;
    -h|--help)
      echo "用法: sudo bash install.sh [--force] [--no-restart]"
      echo "  --force       即使检测到已安装也重新覆盖"
      echo "  --no-restart  安装后不重启 comma.service"
      exit 0 ;;
  esac
done

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; CYN=$'\033[36m'; RST=$'\033[0m'
info() { echo "${CYN}[*]${RST} $*"; }
ok()   { echo "${GRN}[+]${RST} $*"; }
warn() { echo "${YEL}[!]${RST} $*"; }
err()  { echo "${RED}[-]${RST} $*" >&2; }

die() { err "$*"; exit 1; }

# ---------- 0. 环境检查 ----------
[ -d "$OPENPILOT" ] || die "找不到 $OPENPILOT，这不是 comma 设备？"
[ -f "$OPENPILOT/manifest.json" ] || [ -d "$OPENPILOT/selfdrive" ] || die "$OPENPILOT 不像 openpilot 目录"
[ -f "$HERE/manifest.json" ] || die "发布包不完整：缺 manifest.json"

if [ "$(id -u)" -ne 0 ]; then
  die "请用 sudo 运行：sudo bash install.sh"
fi

BASELINE_COMMIT="2589caad342a25f96412ef4027591387ffb06a4a"
info "目标目录: $OPENPILOT"

# 基线提示（非强制）
if [ -f "$OPENPILOT/build.json" ]; then
  CUR_COMMIT=$(grep -o '"git_commit"[^,]*' "$OPENPILOT/build.json" 2>/dev/null | cut -d'"' -f4 || true)
  if [ -n "${CUR_COMMIT:-}" ] && [ "$CUR_COMMIT" != "$BASELINE_COMMIT" ]; then
    warn "当前 commit ($CUR_COMMIT) 与发布包基线 ($BASELINE_COMMIT) 不同"
    warn "补丁可能无法应用。用 --force 可忽略冲突继续。"
    [ "$FORCE" -eq 1 ] || die "已中止。确认要试就加 --force"
  fi
fi

# ---------- 1. 备份 ----------
STAMP="$(date +%Y%m%d-%H%M%S)"
BACKUP="$OPENPILOT/.zh_backup_$STAMP"
info "备份现有文件到 $BACKUP"
mkdir -p "$BACKUP"
python3 - "$HERE" "$OPENPILOT" "$BACKUP" <<'PYEOF'
import json, pathlib, shutil, sys
here, target, backup = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]), pathlib.Path(sys.argv[3])
manifest = json.loads((here / "manifest.json").read_text(encoding="utf-8"))
n = 0
for entry in manifest["entries"]:
    src = target / entry["target"]
    if not src.exists():
        continue
    dst = backup / entry["target"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    n += 1
print(f"  已备份 {n} 个文件")
(backup / ".backup_paths").write_text(
    "\n".join(e["target"] for e in manifest["entries"]), encoding="utf-8")
PYEOF
ok "备份完成"

# ---------- 2. 应用补丁 ----------
info "应用代码补丁"
FAIL=0
for p in "$HERE"/patch/*.patch; do
  [ -f "$p" ] || continue
  name="$(basename "$p")"
  if patch -p1 -d "$OPENPILOT" --dry-run --silent < "$p" >/dev/null 2>&1; then
    patch -p1 -d "$OPENPILOT" --silent < "$p" && ok "  $name"
  elif patch -p1 -d "$OPENPILOT" -R --dry-run --silent < "$p" >/dev/null 2>&1; then
    ok "  $name (已应用，跳过)"
  else
    if [ "$FORCE" -eq 1 ]; then
      warn "  $name 冲突，强制应用（可能产生 .rej）"
      patch -p1 -d "$OPENPILOT" --forward < "$p" || true
    else
      err "  $name 应用失败（用 --force 可强制尝试）"
      FAIL=$((FAIL+1))
    fi
  fi
done
[ "$FAIL" -eq 0 ] || warn "$FAIL 个补丁未能干净应用，检查 $OPENPILOT 下的 .rej 文件"

# ---------- 3. 投放文件 ----------
info "投放新文件与生成物"
python3 - "$HERE" "$OPENPILOT" <<'PYEOF'
import json, pathlib, shutil, sys
here, target = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
manifest = json.loads((here / "manifest.json").read_text(encoding="utf-8"))
n = 0
for entry in manifest["entries"]:
    if entry["kind"] != "drop":
        continue
    src = here / entry["file"]
    if not src.exists():
        print(f"  缺文件: {entry['file']}")
        continue
    dst = target / entry["target"]
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    n += 1
print(f"  已投放 {n} 个文件")
PYEOF
ok "文件投放完成"

# ---------- 4. 权限修正 ----------
info "修正文件所有者"
chown -R comma:comma "$OPENPILOT/selfdrive/ui" "$OPENPILOT/selfdrive/assets" 2>/dev/null || true
chown comma:comma "$OPENPILOT/build.json" 2>/dev/null || true
chown -R comma:comma "$OPENPILOT/system/ui" 2>/dev/null || true
chown -R comma:comma "$OPENPILOT/opendbc_repo/opendbc/car/gm" 2>/dev/null || true
ok "权限已修正"

# ---------- 5. 清缓存 ----------
info "清理 Python 缓存"
find "$OPENPILOT" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
ok "缓存已清理"

# ---------- 6. 设置语言 ----------
info "设置语言为简体中文"
python3 - <<'PYEOF'
import os, pathlib
params = pathlib.Path("/data/params/d")
params.mkdir(parents=True, exist_ok=True)
(params / "LanguageSetting").write_bytes(b"main_zh-CHS")
try:
    os.chown(params / "LanguageSetting", 1000, 1000)
except Exception:
    pass
os.chmod(params / "LanguageSetting", 0o600)
print("  LanguageSetting = main_zh-CHS")
PYEOF
ok "语言已设置"

# ---------- 6b. 车型参数 ----------
info "设置威朗（BUICK_VERANO）所需参数"
python3 - <<'PYEOF'
import os, pathlib
params = pathlib.Path("/data/params/d")
params.mkdir(parents=True, exist_ok=True)
items = {
    # SASCM 车型必须启用 openpilot 纵向控制：SDGM 线束替换了原车 SDGM 模块，
    # 原厂 ACC 链路已断，只能由 openpilot 通过 SASCM 提供纵向。
    "AlphaLongitudinalEnabled": b"1",
    # UI 速度显示校准（vEgoCluster = vEgo * ClusterOffset）。
    # 实测：原车轮速标定与仪表存在约 19% 偏差，此值让界面车速与仪表一致。
    # 注意：只影响显示，不影响控制。换轮胎后需按「仪表 ÷ 设备」重新标定。
    "ClusterOffset": b"1.19",
    # 这两项出厂默认是 1，但实测设备上被置成了 0，导致：
    #   · 红灯前不减速
    #   · 前方静止车辆不响应
    # 恢复为 1 后才能配合 VERANO_STOPPING_TUNE 实现完整刹停。
    "CEStopLights": b"1",
    "CEStoppedLead": b"1",
}
for k, v in items.items():
    p = params / k
    p.write_bytes(v)
    try:
        os.chown(p, 1000, 1000)
    except Exception:
        pass
    os.chmod(p, 0o600)
    print(f"  {k} = {v.decode()}")
PYEOF
ok "车型参数已设置"

# ---------- 6c. 恢复出厂保护 ----------
info "关闭 comma.sh 的「触摸计数触发恢复出厂」"
CS=/usr/comma/comma.sh
if [ ! -f "$CS" ]; then
  warn "  找不到 $CS（非 AGNOS？），跳过"
elif grep -q ".allow_tap_reset" "$CS" 2>/dev/null; then
  ok "  已修补过，无需重复"
else
  REMOUNTED=0
  if mount -o rw,remount / 2>/dev/null; then REMOUNTED=1; fi
  python3 - "$CS" <<'PYEOF'
import pathlib, sys
p = pathlib.Path(sys.argv[1])
t = p.read_text(encoding="utf-8", errors="replace")
old = '  elif (( "$(cat /sys/class/input/input2/device/touch_count)" > 4 )); then'
new = ('  # [patched] tap-reset 改为 opt-in：需存在 /data/.allow_tap_reset 才生效\n'
       '  # 原因：touch_count 是内核累计计数，跨重启不清零，会在开机时误触发工厂重置。\n'
       '  elif [ -f /data/.allow_tap_reset ] && (( "$(cat /sys/class/input/input2/device/touch_count)" > 4 )); then')
if old in t:
    p.write_text(t.replace(old, new, 1), encoding="utf-8")
    print("  已把 tap-reset 改为 opt-in")
else:
    print("  ⚠ 未找到目标分支（comma.sh 版本不同？），跳过")
PYEOF
  if [ "$REMOUNTED" -eq 1 ]; then
    bash -n "$CS" && ok "  comma.sh 语法 OK"
    mount -o ro,remount / 2>/dev/null || true
  fi
  ok "  恢复出厂保护处理完毕（如需重新启用：sudo touch /data/.allow_tap_reset）"
fi

# ---------- 7. 重启 ----------
if [ "$NO_RESTART" -eq 0 ]; then
  info "重启 comma.service"
  systemctl restart comma.service || warn "重启失败，请手动：sudo systemctl restart comma.service"
  sleep 5
  ok "已重启"
else
  warn "按 --no-restart 跳过重启。手动执行：sudo systemctl restart comma.service"
fi

echo
ok "安装完成！"
echo "  备份目录: $BACKUP"
echo "  回滚:     sudo bash $HERE/uninstall.sh $BACKUP"
echo "  查看日志: journalctl -u comma -f"
