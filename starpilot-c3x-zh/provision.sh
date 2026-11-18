#!/usr/bin/env bash
# 刷机后一键部署：AGNOS → StarPilot → 汉化补丁
#
# 运行位置：设备上（SSH），需 root
#   sudo bash provision.sh                 # 智能模式：缺什么补什么
#   sudo bash provision.sh --full          # 强制全量（clone + 依赖 + acados）
#   sudo bash provision.sh --patch-only    # 只装汉化补丁
#   sudo bash provision.sh --check         # 只检查环境，不改动
#
# 环境变量：
#   REPO / BRANCH / COMMIT  目标打开 openpilot 仓库（默认 StarPilot@StarPilot 基线）
set -uo pipefail

REPO="${REPO:-https://github.com/StarPilotHQ/StarPilot.git}"
BRANCH="${BRANCH:-StarPilot}"
COMMIT="${COMMIT:-2589caad342a25f96412ef4027591387ffb06a4a}"
OPENPILOT="${OPENPILOT_DIR:-/data/openpilot}"
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
LOG=/data/provision-$(date +%Y%m%d-%H%M%S).log

MODE=auto
RUN_SETUP=auto
NO_RESTART=0
for arg in "$@"; do
  case "$arg" in
    --full) MODE=full ;;
    --patch-only) MODE=patch ;;
    --check) MODE=check ;;
    --no-setup) RUN_SETUP=0 ;;
    --no-restart) NO_RESTART=1 ;;
    -h|--help) sed -n '2,16p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0 ;;
  esac
done

RED=$'\033[31m'; GRN=$'\033[32m'; YEL=$'\033[33m'; CYN=$'\033[36m'; RST=$'\033[0m'
info() { echo "${CYN}[*]${RST} $*"; }
ok()   { echo "${GRN}[+]${RST} $*"; }
warn() { echo "${YEL}[!]${RST} $*"; }
err()  { echo "${RED}[-]${RST} $*" >&2; }
die()  { err "$*"; exit 1; }
stage() { echo; echo "${CYN}══ $* ══${RST}"; }

exec > >(tee -a "$LOG") 2>&1
echo "日志: $LOG"

# ───────────────────────────── 0. 前置检查
stage "0. 环境检查"

[ -f /AGNOS ] || [ -d /usr/comma ] || die "这不是 comma AGNOS 设备"
ok "AGNOS 设备"

if [ "$MODE" = check ]; then
  stage "环境检查结果（只读，未改动任何文件）"
  echo "  仓库: $REPO"
  echo "  分支: $BRANCH"
  echo "  基线: ${COMMIT:0:8}"
  echo "  补丁包: $HERE"
  echo
  for item in "$OPENPILOT" "$OPENPILOT/.git" "$OPENPILOT/build.json" \
              "$OPENPILOT/third_party/acados/larch64/lib/libacados.so" \
              "$OPENPILOT/pyproject.toml" "$OPENPILOT/tools/setup.sh" \
              "/data/continue.sh" "/data/params/d/LanguageSetting" \
              "$OPENPILOT/selfdrive/ui/translations/app_zh-CHS.po" \
              "$OPENPILOT/selfdrive/ui/widgets/vehicle_status.py"; do
    if [ -e "$item" ]; then ok "  $item"; else warn "  缺失: $item"; fi
  done
  echo
  if [ -d "$OPENPILOT/.git" ]; then
    echo "  当前 HEAD: $(git -C "$OPENPILOT" rev-parse --short HEAD 2>/dev/null) $(git -C "$OPENPILOT" log -1 --format='%s' 2>/dev/null | cut -c1-60)"
  fi
  echo "  可用空间 /data: $(df -h /data 2>/dev/null | awk 'NR==2{print $4}')"
  exit 0
fi

[ "$(id -u)" -eq 0 ] || die "请用 sudo 运行（只读检查请用 --check）"

. /etc/profile 2>/dev/null || true
export PATH="/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin"

PY=/usr/local/venv/bin/python3
[ -x "$PY" ] || die "找不到 $PY（AGNOS 的 venv 缺失）"
ok "Python: $($PY --version 2>&1)"

FREE_KB=$(df -k /data 2>/dev/null | awk 'NR==2{print $4}')
info "  /data 可用: $((FREE_KB/1024)) MB"

command -v git >/dev/null || die "缺少 git"
command -v uv  >/dev/null || warn "缺少 uv，依赖安装可能失败"

if ! timeout 12 curl -sfI https://github.com >/dev/null 2>&1; then
  warn "GitHub 不可达 —— 若已安装 openpilot 可继续；否则请先联网"
fi

# ───────────────────────────── 1. 取得 openpilot 树
stage "1. openpilot 源码树"

need_clone=0
if [ ! -d "$OPENPILOT" ]; then
  need_clone=1
elif [ ! -d "$OPENPILOT/.git" ]; then
  warn "$OPENPILOT 存在但不是 git 仓库（可能是 tarball）"
  [ "$MODE" = patch ] && die "补丁模式需要 git 树" 
  need_clone=1
fi

if [ "$need_clone" = 1 ]; then
  [ "$MODE" = patch ] && die "补丁模式要求 $OPENPILOT 已存在"
  if [ -d "$OPENPILOT" ]; then
    BAK="$OPENPILOT.notgit.$(date +%s)"
    warn "把现有目录移到 $BAK"
    mv "$OPENPILOT" "$BAK" || die "移动失败"
  fi
  info "克隆 $REPO"
  git clone --filter=blob:none "$REPO" "$OPENPILOT" || die "克隆失败（检查网络）"
fi

cd "$OPENPILOT" || die "无法进入 $OPENPILOT"

CUR_ORIGIN=$(git remote get-url origin 2>/dev/null || echo "")
if [ "$CUR_ORIGIN" != "$REPO" ]; then
  info "切换 origin: $CUR_ORIGIN -> $REPO"
  git remote set-url origin "$REPO" 2>/dev/null || git remote add origin "$REPO"
fi

info "拉取 $BRANCH"
git fetch origin "$BRANCH" --depth 200 2>/dev/null || git fetch origin "$BRANCH" || die "fetch 失败"

if [ -n "$COMMIT" ]; then
  if git cat-file -e "${COMMIT}^{commit}" 2>/dev/null; then
    git checkout -q "$COMMIT" 2>/dev/null || die "checkout $COMMIT 失败"
    ok "已切到基线 ${COMMIT:0:8}"
  else
    warn "基线 ${COMMIT:0:8} 不在本地，改用分支 HEAD"
    git checkout -q -B "$BRANCH" "origin/$BRANCH" || die "checkout 分支失败"
  fi
else
  git checkout -q -B "$BRANCH" "origin/$BRANCH" || die "checkout 分支失败"
fi

ACTUAL=$(git rev-parse HEAD)
if [ -n "$COMMIT" ] && [ "$ACTUAL" != "$COMMIT" ]; then
  warn "当前 HEAD $ACTUAL 与发布包基线 ${COMMIT:0:8} 不同"
  warn "补丁可能无法干净应用；用 install.sh --force 可强制尝试"
fi
ok "源码树: $(git log -1 --format='%h %s' | cut -c1-70)"

# ───────────────────────────── 2. build.json
stage "2. 构建元数据"

if [ ! -f build.json ]; then
  info "生成 build.json（tarball/浅克隆树必需）"
  cat > build.json <<JSON
{
  "channel": "StarPilot",
  "openpilot": {
    "version": "0.10.3",
    "release_notes": "StarPilot (raylib UI) via provision.sh",
    "git_commit": "$ACTUAL",
    "git_origin": "$REPO",
    "build_style": "unknown",
    "is_dirty": false
  }
}
JSON
  chown comma:comma build.json 2>/dev/null || true
  ok "build.json 已生成"
else
  ok "build.json 已存在"
fi

# ───────────────────────────── 3. 依赖与 acados
stage "3. Python 依赖与 acados"

need_setup=0
ACADOS_LIB=$(ls third_party/acados/*/lib/libacados.so 2>/dev/null | head -1)
[ -n "$ACADOS_LIB" ] || need_setup=1
[ -f pyproject.toml ] || need_setup=1

if [ "$RUN_SETUP" = 0 ]; then
  warn "按 --no-setup 跳过"
elif [ "$need_setup" = 0 ] && [ "$MODE" != full ]; then
  ok "依赖与 acados 已就绪，跳过"
else
  if [ ! -f tools/setup.sh ]; then
    warn "缺少 tools/setup.sh，跳过依赖安装"
  else
    info "运行 tools/setup.sh（可能需要 10-20 分钟）"
    # 已知问题：acados 里的 coding: future_fstrings 会让旧 Python 报编码错误
    if grep -rl "coding: future_fstrings" third_party/acados 2>/dev/null | head -1 >/dev/null; then
      info "  清理 acados 里的 future_fstrings 编码声明"
      grep -rl "coding: future_fstrings" third_party/acados 2>/dev/null \
        | xargs -r sed -i '/coding: future_fstrings/d'
    fi
    chmod +x tools/setup.sh
    bash tools/setup.sh 2>&1 | tail -40
    SETUP_RC=${PIPESTATUS[0]}
    if [ "$SETUP_RC" -ne 0 ]; then
      warn "tools/setup.sh 返回 $SETUP_RC（可能部分完成，继续尝试）"
    fi
    ACADOS_AFTER=$(ls third_party/acados/*/lib/libacados.so 2>/dev/null | head -1)
    [ -n "$ACADOS_AFTER" ] && ok "acados 已构建: $ACADOS_AFTER" || warn "acados 未构建"
  fi
fi

# ───────────────────────────── 4. continue.sh
stage "4. 启动脚本"

mkdir -p /data
cat > /data/continue.sh <<'SH'
#!/usr/bin/env bash

cd /data/openpilot
exec ./launch_openpilot.sh
SH
chmod +x /data/continue.sh
chown comma:comma /data/continue.sh 2>/dev/null || true
ok "/data/continue.sh 已写入"

# ───────────────────────────── 5. 参数
stage "5. 设备参数"

param() {  # param KEY VALUE
  local k="$1" v="$2" p="/data/params/d/$k"
  mkdir -p /data/params/d
  printf '%s' "$v" > "$p"
  chmod 600 "$p" 2>/dev/null || true
  chown comma:comma "$p" 2>/dev/null || true
  echo "    $k = $v"
}

param LanguageSetting main_zh-CHS
param IsMetric 1
[ -f /tmp/skip_branch_param ] || true

# 让系统更新器指向我们的分支
if [ -d .git ]; then
  git config --local committer.email "comma@comma.ai" 2>/dev/null || true
fi
ok "参数已设置"

# ───────────────────────────── 6. 汉化补丁
stage "6. 汉化补丁"

if [ -f "$HERE/install.sh" ]; then
  info "运行 $HERE/install.sh"
  bash "$HERE/install.sh" --no-restart --force || warn "install.sh 返回非零"
else
  warn "当前目录没有 install.sh，跳过补丁安装"
fi

# ───────────────────────────── 7. 重启与验证
stage "7. 重启与验证"

chown -R comma:comma "$OPENPILOT" 2>/dev/null || warn "chown 失败（可能耗时较长，可忽略）"
find "$OPENPILOT" -name "__pycache__" -type d -prune -exec rm -rf {} + 2>/dev/null || true

if [ "$NO_RESTART" -eq 0 ]; then
  info "重启 comma.service"
  systemctl restart comma.service
  sleep 8
fi

echo
for check in \
  "params:/data/params/d/LanguageSetting" \
  "po:/data/openpilot/selfdrive/ui/translations/app_zh-CHS.po" \
  "font:/data/openpilot/selfdrive/assets/fonts/NotoSansSC-Regular.png" \
  "panel:/data/openpilot/selfdrive/ui/widgets/vehicle_status.py" \
  "continue:/data/continue.sh"; do
  name="${check%%:*}"; path="${check#*:}"
  if [ -e "$path" ]; then ok "  $name ✓"; else warn "  $name 缺失: $path"; fi
done

if pgrep -f "selfdrive.ui.ui" >/dev/null; then
  ok "  UI 进程在运行 (pid $(pgrep -f 'selfdrive.ui.ui' | head -1))"
else
  warn "  UI 进程未运行，查看: journalctl -u comma -n 80"
fi

echo
ok "部署完成"
echo "  日志: $LOG"
echo "  验证: sudo bash $HERE/tools/verify.sh   (若存在)"
echo "  回滚: sudo bash $HERE/uninstall.sh"
