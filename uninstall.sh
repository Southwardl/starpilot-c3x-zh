#!/usr/bin/env bash
# 回滚：从 install.sh 创建的备份目录恢复
# 用法: sudo bash uninstall.sh [备份目录] [--no-restart]
set -uo pipefail

OPENPILOT="${OPENPILOT_DIR:-/data/openpilot}"
NO_RESTART=0
BACKUP=""
for arg in "$@"; do
  case "$arg" in
    --no-restart) NO_RESTART=1 ;;
    -h|--help)
      echo "用法: sudo bash uninstall.sh <备份目录> [--no-restart]"
      echo "  备份目录形如 $OPENPILOT/.zh_backup_20261118-001234"
      exit 0 ;;
    *) BACKUP="$arg" ;;
  esac
done

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; CYN=$'\033[36m'; RST=$'\033[0m'
info() { echo "${CYN}[*]${RST} $*"; }
ok()   { echo "${GRN}[+]${RST} $*"; }
warn() { echo "${YEL}[!]${RST} $*"; }
die()  { echo "${RED}[-]${RST} $*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "请用 sudo 运行"

if [ -z "$BACKUP" ]; then
  BACKUP="$(ls -dt "$OPENPILOT"/.zh_backup_* 2>/dev/null | head -1)"
  [ -n "$BACKUP" ] || die "找不到备份目录。请把备份路径作为参数传入。"
  warn "未指定备份目录，使用最新的: $BACKUP"
fi
[ -d "$BACKUP" ] || die "备份目录不存在: $BACKUP"

info "从 $BACKUP 恢复"
n=0
while IFS= read -r rel; do
  [ -n "$rel" ] || continue
  src="$BACKUP/$rel"
  if [ -f "$src" ]; then
    mkdir -p "$(dirname "$OPENPILOT/$rel")"
    cp -p "$src" "$OPENPILOT/$rel"
    n=$((n+1))
  fi
done < "$BACKUP/.backup_paths"
ok "已恢复 $n 个文件"

info "清理 Python 缓存"
find "$OPENPILOT" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true
chown -R comma:comma "$OPENPILOT/selfdrive/ui" "$OPENPILOT/selfdrive/assets" 2>/dev/null || true

if [ "$NO_RESTART" -eq 0 ]; then
  info "重启 comma.service"
  systemctl restart comma.service || warn "重启失败，请手动执行"
fi

ok "回滚完成"
