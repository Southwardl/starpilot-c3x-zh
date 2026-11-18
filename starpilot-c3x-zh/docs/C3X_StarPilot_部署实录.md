# C3X 部署 StarPilot 0.10.3 完整实录

> 记录时间：2026-11-17
> 设备：comma 3X（`comma tizi`），序列号 `5e0dca10`，MAC `00:0a:f5:b4:cc:6f`
> 结果：**成功** —— AGNOS 16 + StarPilot 0.10.3 完整运行，含纵向控制与红绿灯 CEM

---

## 一、最终状态

| 项目 | 值 |
|---|---|
| 机型 | `comma tizi`（comma 3X） |
| Hostname | `comma-5e0dca10` |
| **AGNOS** | **16**（Ubuntu 24.04.3 LTS，kernel 4.9.103） |
| **openpilot** | **0.10.3 / StarPilot** |
| Commit | `2951d40faca3dd12167ad552e2d1b0d8f9670c5c` |
| Remote | `https://github.com/firestar5683/StarPilot.git` |
| 启动槽 | `_b` |
| DongleId | `sky_ef7kjnxxwdie`（见"待办"） |
| 车型 | `Buick LaCrosse 2017-19 ASCM Harness` |
| 显示 | weston active，UI 正常运行，背光由 UI 自动控制 |

### 关键功能参数

| 参数 | 值 | 含义 |
|---|---|---|
| `AlphaLongitudinalEnabled` | 1 | **openpilot 纵向控制总开关** |
| `ConditionalExperimental` | 1 | **CEM 条件实验模式（红绿灯自动切换）** |
| `CEStopLights` | 1 | **红绿灯触发条件** |
| `CEModelStopTime` | 7.0 | 红绿灯停止时间阈值 |
| `LongitudinalPersonality` | 1 | 跟车风格（标准） |
| `ExperimentalModeConfirmed` | 1 | 已确认实验模式 |

### 运行进程（22 个）

```
manager.py ×2          ui                pandad ×2
logmessaged            timed             loggerd.deleter / uploader
hardwared              tombstoned        updated
statsd                 cloudlink.supportd  athenad
the_pond               galaxy            device_syncd
starpilot_process      mapd_wrapper      mapd
```

---

## 二、为什么这么难 —— 三次失败尝试

背景：fork 的 AGNOS CDN `apac-cl.beartech.ca` 从始至终不可达（HTTP 000/523），
而 StarPilot 0.10.3 需要 AGNOS `12.8.16`（fork 自定义构建，只托管在那个 CDN 上）。

| # | 方案 | 结果 | 卡点 |
|---|---|---|---|
| 1 | 从 C3 拷贝预编译树到 AGNOS 12.8 | 核心进程能跑 | UI 缺 `libOmxCore` |
| 2 | 刷 comma 官方 AGNOS 16（v0.10.3 配套） | 核心进程能跑 | UI 缺 `libOmxCore`，且只用了 `LD_LIBRARY_PATH`（manager 子进程拿不到） |
| 3 | 在 AGNOS 19.9 上重新编译 StarPilot | **编译 100% 成功** | AGNOS 19.9 **没有 Wayland 显示栈**（新版改用 raylib+EGL 直连） |
| 4 | **AGNOS 16 + C3 原始树 + 系统级装库**（最终方案） | **全部成功** | — |

**结论**：StarPilot 0.10.3 是「AGNOS 12.8.x 时代 + Wayland 显示栈 + Qualcomm OMX 库」的配套产物，三个条件必须同时满足。

---

## 三、五个关键坑（逐个拆解）

### 坑 1：`libOmxCore.so` 缺失 —— 必须装进系统目录

**现象**
```
./ui: error while loading shared libraries: libOmxCore.so: cannot open shared object file
```

**原因**：StarPilot 的 UI 链接 Qualcomm OMX 库，而这库在 comma 官方 AGNOS 里**根本不存在**
（是 fork 自定义 AGNOS 才有的）。源码树里只带**头文件**
（`starpilot/ui/screenrecorder/openmax/include/OMX_Core.h`），不带 `.so`。

**错误做法**：`LD_LIBRARY_PATH=/data/oplibs` —— 手动跑 UI 能活，但 **manager spawn 子进程时环境被清理**，无效。

**正确做法**：直接装进系统库目录
```bash
sudo cp /data/oplibs/*.so* /usr/lib/aarch64-linux-gnu/
sudo ldconfig
```
- 库来源：从运行 StarPilot 的 C3 上拷出的 13 个文件（`libOmx*.so` + `libmm-*`）
- 同时解决**链接期**（`-lOmxCore`）和**运行期**两个问题

### 坑 2：`weston` 服务默认不启动，且根分区只读

**现象**：`systemctl enable --now weston` → `Failed to enable unit: Read-only file system`
（注意：`enable` 失败会连带 `--now` 一起放弃，所以 weston 根本没启动）

**正确做法**：
```bash
sudo mount -o rw,remount /
sudo systemctl enable weston weston-ready
sudo systemctl start weston
```

**重要**：weston 必须在 UI 之前起来，`comma.sh` 会等 `weston-ready`。

### 坑 3：Wayland socket 权限 —— UI 静默退出 `rc=0`（最隐蔽）

**现象**：UI 反复 `exitcode 0` 重启，**没有任何输出**。

**原因**：fork 在 `selfdrive/ui/main.cc` 里加了这段：
```cpp
void waylandAwareMessageHandler(QtMsgType type, ...) {
  if (type == QtCriticalMsg || type == QtFatalMsg) {
    if (bytes.contains("ayland") || bytes.contains("wl_display")) {
      LOGE("UI WAYLAND EXIT: %s", ...);
      _exit(0);            // ← 干净退出，所以看起来像正常结束
    }
  }
}
```

而真实错误在 swaglog 里：
```
UI WAYLAND EXIT: Failed to create wl_display (Permission denied)
```

**原因**：`weston.service` 没有 `User=`（以 **root** 运行），socket 权限是
`srwxr-xr-x root:root` —— **Unix socket 连接需要写权限**，`comma`(uid 1000) 连不上。

**正确做法**：加 systemd drop-in 把 umask 设为 0
```bash
sudo mkdir -p /etc/systemd/system/weston.service.d
sudo tee /etc/systemd/system/weston.service.d/umask.conf <<'EOF'
[Service]
UMask=0000
EOF
sudo systemctl daemon-reload
sudo systemctl restart weston
# 验证：srwxrwxrwx root root /var/tmp/weston/wayland-0
```

### 坑 4：`/dev/shm` 里残留 root 属主的 msgq 文件 → UI `SIGABRT(-6)`

**现象**：`Process ui crashed with exitcode -6`

**原因**：调试期间用 root 跑过 UI，在 `/dev/shm` 留下 `root:root 644` 的 `msgq_*` 文件；
`comma` 用户打不开 → `SubSocket` 失败 → 断言 → abort。

```
-rw-r--r-- 1 root  root   256384 msgq_bookmarkButton   ← 罪魁
-rw-r--r-- 1 comma comma 10486144 msgq_can              ← 正常的
```

**正确做法（调试后必做）**：
```bash
sudo find /dev/shm -user root -name "msgq_*" -delete
sudo systemctl restart comma.service
```

### 坑 5：参数文件属主错误 → manager 起不来

**现象**
```
shutil.Error: [('/data/params/d/IsRHD', '/tmp/.../d/IsRHD',
  "[Errno 13] Permission denied: '/data/params/d/IsRHD'")]
```

**原因**：用 `sudo tar` 恢复参数备份 → 文件变成 `root:root`，而 `comma.service` 以 `User=comma` 运行。

**正确做法**：
```bash
sudo chown -R comma:comma /data/params
sudo find /data/params -type f -exec chmod 600 {} \;
```

> 注意：`chown -R` 偶尔会静默失败，务必用 `stat` 逐个确认，别只看命令返回码。

---

## 四、从零复现步骤

前提：设备已是 AGNOS 19.9 + 官方 openpilot（9008 刷机后的状态），且槽 B 已刷入 AGNOS 16。

### 步骤 1：准备 StarPilot 树

```bash
# 把 C3 备份的树解到 /data
tar -xf /data/c3_tree.tar -C /data/openpilot.c3_stock --strip-components=1

# AGNOS 版本号必须与目标系统一致，否则启动时会去尝试刷 AGNOS
sed -i 's/export AGNOS_VERSION="12.8.16"/export AGNOS_VERSION="16"/' \
  /data/openpilot.c3_stock/launch_env.sh

# 换掉当前树
sudo systemctl stop comma.service
mv /data/openpilot /data/openpilot.stock_0919
mv /data/openpilot.c3_stock /data/openpilot
```

### 步骤 2：把 OMX 库装进**槽 B 的系统分区**（在切槽之前做）

```bash
sudo mount -o rw /dev/disk/by-partlabel/system_b /mnt
sudo cp -f /data/oplibs/*.so* /mnt/usr/lib/aarch64-linux-gnu/
sudo sync && sudo umount /mnt
```

### 步骤 3：切槽并重启

```bash
sudo abctl --set_active 1     # 切到槽 B
sudo reboot
```

### 步骤 4：启动后修系统（AGNOS 16 上）

```bash
# 4.1 根分区改可写
sudo mount -o rw,remount /

# 4.2 weston drop-in（关键！）
sudo mkdir -p /etc/systemd/system/weston.service.d
sudo tee /etc/systemd/system/weston.service.d/umask.conf <<'EOF'
[Service]
UMask=0000
EOF

# 4.3 启用 weston
sudo systemctl daemon-reload
sudo systemctl enable weston weston-ready
sudo systemctl start weston

# 4.4 修参数属主
sudo chown -R comma:comma /data/params
sudo find /data/params -type f -exec chmod 600 {} \;

# 4.5 清 /dev/shm 残留
sudo find /dev/shm -user root -name "msgq_*" -delete

# 4.6 启动 openpilot
sudo systemctl restart comma.service
```

### 步骤 5：验证

```bash
ps -eo cmd | grep -E '\./ui$|starpilot'    # 应有 ./ui 和 7 个 starpilot 进程
systemctl is-active weston                  # 应为 active
cat /sys/class/backlight/*/brightness       # UI 会自己设置（>0 即正常）
```

---

## 五、验证清单

| 检查项 | 命令 | 期望 |
|---|---|---|
| AGNOS 版本 | `cat /VERSION` | `16` |
| openpilot 版本 | `cat /data/params/d/Version` | `0.10.3` |
| 分支 | `cat /data/params/d/GitBranch` | `StarPilot` |
| weston | `systemctl is-active weston` | `active` |
| socket 权限 | `ls -la /var/tmp/weston/wayland-0` | `srwxrwxrwx` |
| UI | `ps -eo cmd \| grep '\./ui$'` | 有进程 |
| 崩溃计数 | `grep -c 'ui crashed' $(ls -t /data/log/swaglog.* \| head -1)` | **0** |
| Wayland 错误 | `grep -c 'WAYLAND EXIT' ...` | **0** |
| 车型 | `cat /data/params/d/CarModelName` | `Buick LaCrosse 2017-19 ASCM Harness` |
| 纵向开关 | `cat /data/params/d/AlphaLongitudinalEnabled` | `1` |

---

## 六、回滚方案

槽 A 完好保留着**原厂 openpilot 0.11.2 + AGNOS 19.9**。

```bash
# 1. 切回槽 A
sudo abctl --set_active 0

# 2. 恢复原厂树（如果槽 A 启动后发现 openpilot 跑的是 StarPilot）
sudo systemctl stop comma.service
mv /data/openpilot /data/openpilot.starpilot
mv /data/openpilot.stock_0919 /data/openpilot

# 3. 重启
sudo reboot
```

**验证**：`cat /VERSION` → `19.9`，`abctl --boot_slot` → `_a`

---

## 七、备份清单（本地 `D:\ds_harness\`）

### 来自 C3（已离线，此为其全部遗物）

| 文件 | 大小 | 内容 |
|---|---|---|
| `c3_openpilot_tree_2026-11-17.tar` | 735 MB | **整棵 openpilot 树**（已编译，sha256 `8188159c…b8b0e33c`） |
| `c3_full_backup_2026-11-16.zip` | 495 KB | 547 个参数 + etc 配置 + 迁移分级 |
| `c3_full_backup_2026-11-16/` | 829 KB | 同上，已解压 |
| `c3_fingerprint_backup_2026-11-16/` | 27 KB | 车型指纹 + `CarParamsPersistent.bin` + 还原脚本 |
| `c3_ssh/` | 4 KB | SSH 接入材料 |
| `C3_openpilot_tree_备份说明.md` | — | 上面那份的说明 |

### 本次会话产出

| 文件 | 内容 |
|---|---|
| `C3X_StarPilot_部署实录.md` | **本文档** |
| `c3x_starpilot_migration/params_pkg.tar.gz` | 462 项可迁移参数 |

### 设备本地

| 路径 | 大小 | 说明 |
|---|---|---|
| `/data/openpilot` | 752 MB | **运行中的 StarPilot 树** |
| `/data/openpilot.stock_0919` | 598 MB | 原厂 0.11.2 树（回滚用） |
| `/data/c3_tree.tar` | 735 MB | C3 原始树 tar（可删） |
| `/data/openpilot.starpilot_rebuilt` | 802 MB | 在 19.9 上重编译的实验版（**可删**） |
| `/data/oplibs` | 1.3 MB | OMX 库原始拷贝（可删） |

---

## 八、待办与已知问题

### ⚠️ 1. 根分区已满（100%）

```
/dev/root  4.3G  4.1G  0  100% /
```

装构建依赖（scons/capnproto/eigen/ffmpeg-dev）导致。`/usr/lib` 2.0G、`/usr/local` 1.1G（venv）。

**风险**：openpilot 主要写 `/data`，暂时不影响；但根分区满可能引发偶发故障。

**清理建议**（按风险从低到高）：
```bash
sudo apt-get clean                    # 清 apt 缓存
sudo apt-get autoremove               # 清无用依赖
# 谨慎：卸载 capnproto/libcapnp-dev 可能影响已链接的二进制
```

### ⚠️ 2. DongleId 变成了 `sky_ef7kjnxxwdie`

三个 dongle id 参数全部是这个值，前缀 `sky_` 不是 comma 官方格式。
推测是 9008 刷机（第三方镜像 `flash13.mr-one.cn`，即 comma 官方 flash.comma.ai 的国内镜像）时写入的。

**影响**：云端配对、上传可能走的是第三方服务而非 comma connect。

**建议**：如需使用 comma connect，检查 `DongleId` / `StockDongleId` 是否应恢复为原厂 id。

### ⚠️ 3. 未上车验证

以下只能在实车上确认：
- [ ] 车辆能否正确识别（`CarModelName` 已是 Buick LaCrosse）
- [ ] `GMFlags.SASCM` 是否置位（决定 ASCM-INT 纵向路径是否启用）
- [ ] 纵向控制是否真的接管油门刹车
- [ ] CEM 红绿灯是否按预期触发（界面边框变**橙色** + 出现**红绿灯 widget**）

### ⚠️ 4. 未做重启持久性验证

关键配置（weston 的 `enable`、umask drop-in、系统库）都写进了槽 B 根分区，
理论上重启后自动生效，但**尚未实测重启**。

---

## 九、安全提醒（重要）

1. **绝不在车辆通电时重启/断电设备** —— 会触发 LKAS 故障（需开关车门等约 2 分钟清除）

2. **红绿灯功能是"辅助"级别**。官方原文：
   > "It will stop at **most** traffic lights"
   > "Experimental mode... is **not recommended at the moment**. It may brake or accelerate erratically."

   **红灯前必须随时准备自己踩刹车。**

3. **CEM 是推荐用法**（自动在接近红绿灯时切入实验模式），不要常开 experimental mode。

4. **不要在 AGNOS 19.9 上手动启动 weston** —— 新版显示栈是 raylib+EGL 直连 DRM，
   weston 会抢占 DRM master 导致原厂 UI 报 `EGL initialization failed`，设备卡在开机 logo。

---

## 十、屏幕自动熄灭问题（2026-11-17 修复）

### 现象

用户反馈"重启后有几次无法进入系统"。实际排查结论：**系统每次都正常启动，是屏幕自己变黑了。**

### 诊断证据

| 证据 | 结论 |
|---|---|
| `/data/media/0/realdata/boot/` 启动日志编号连续（十六进制 `0a`→`19`） | 每次开机 openpilot 都成功启动 |
| UI 进程稳定运行，`ui crashed = 0` | 系统完全正常 |
| **背光 `0/1023`** | 屏幕全黑 |
| `ScreenTimeout = 30` | 停车 30 秒无触摸即熄屏 |

### 根因

`selfdrive/ui/ui.cc` 第 514 行：

```cpp
if (!awake) brightness = 0;
...
setAwake(s.scene.started || interactive_timeout > 0);
```

停车状态（`scene.started == false`）下，`interactive_timeout` 走完就 `awake = false`，背光直接归零。
**点一下屏幕就会亮** —— 这是 StarPilot 的"停车熄屏"特性，不是故障。

### 修复（两层）

**第一层：参数调到上限**

```bash
printf '60' > /data/params/d/ScreenTimeout
printf '60' > /data/params/d/ScreenTimeoutOnroad
```

UI 控件的取值范围是 5–60 秒，没有"永不熄屏"选项。

**第二层：源码补丁（让 60 秒 = 常亮）**

改 `selfdrive/ui/ui.cc` 第 514 行：

```cpp
// 原文
setAwake(s.scene.started || interactive_timeout > 0);
// 改后
setAwake(s.scene.started || interactive_timeout > 0 || screen_timeout >= 60);
```

把 `ScreenTimeout` 设为上限 60 时，停车状态保持常亮。

重新编译（只改一个文件，约 1–2 分钟）：

```bash
cd /data/openpilot
export SP_QT_HOST_LRELEASE=/usr/local/bin/lrelease-iso
rm -f selfdrive/ui/ui
scons -u -j4 selfdrive/ui/ui
sudo systemctl restart comma.service
```

### 验证

背光连续 **90 秒**保持 `511/1023`（此前 30–60 秒内必归零），UI 进程全程运行，零崩溃。

### 回滚

```bash
cp /data/ui.cc.orig /data/openpilot/selfdrive/ui/ui.cc   # 源码还原
cp /data/ui.orig    /data/openpilot/selfdrive/ui/ui      # 二进制还原
```

> ⚠️ 该补丁是本地修改。日后若重新安装/更新 StarPilot，补丁会丢失，需重新应用。

---

## 十一、AGNOS 图形栈架构（极其重要）

### 架构：magic 是 DRM 的"总代理"

AGNOS 的显示不是直接由 weston/UI 打开 `/dev/dri/card0`，而是经过 `magic`：

```
magic.py（Python + raylib）
  ├─ 打开 /dev/dri/card0
  ├─ 显示 /usr/comma/bg.png（开机 logo）
  └─ 监听 /tmp/drmfd.sock
        ↓ 客户端连接时
     通过 SCM_RIGHTS 把 DRM master 的 fd 传给它
        ↓
   weston（AGNOS 16）或 raylib UI（AGNOS 19.9）拿到 fd 才能渲染
```

**关键推论**：
- `magic` 起不来 → 整个 UI 无法渲染 → **屏幕停在开机画面或全黑**
- 症状看起来像"系统没启动"，其实系统全好，只是显示通路断了
- 开机日志里 `raylib: COMMA: Failed to connect to magic` / `Failed to initialize drm` 就是它

### ⚠️ 绝对不要安装 Mesa 的 GL/EGL/GBM 包

**这是本次事故的根本原因。**

在 AGNOS 上执行 `apt-get install` 时，以下包会**把 Adreno 的图形库替换成 Mesa**：

```
libegl1-mesa-dev   libgles2-mesa-dev   libegl-mesa0   libegl1   libgbm-dev
```

而被替换的正是 Adreno GPU 唯一可用的驱动：

| 库 | 正确指向（Adreno/AGNOS） | 被 Mesa 替换后 |
|---|---|---|
| `libEGL.so.1` | `libEGL.so.1.0.0` → `libEGL_adreno.so` | `libEGL.so.1.1.0`（Mesa） |
| `libGLESv2.so.2` | `libGLESv2.so.2.0.0` → `libGLESv2_adreno.so` | `libGLESv2.so.2.1.0`（Mesa） |
| `libgbm.so.1` | `libgbm.so`（AGNOS 原版，SONAME=`libgbm.so`） | `libgbm.so.1.0.0`（Mesa） |

**后果链**：

```
Mesa 库覆盖 Adreno 驱动
  → magic 报 "Failed to find correct config" / "Failed to initialize EGL"
  → magic 进程退出，/tmp/drmfd.sock 不存在
  → UI 拿不到 DRM fd → EGL 初始化失败 → 崩溃
  → 屏幕停在开机画面 / 全黑（看起来像"卡在开机界面"）
```

### 修复步骤

```bash
sudo mount -o rw,remount /

# 1) 删除 Mesa 的 EGL/GLES 库和 glvnd 的 Mesa vendor 配置
sudo rm -f /usr/lib/aarch64-linux-gnu/libEGL.so.1.1.0
sudo rm -f /usr/lib/aarch64-linux-gnu/libGLESv2.so.2.1.0
sudo rm -f /usr/lib/aarch64-linux-gnu/libEGL_mesa.so.0*
sudo rm -f /usr/share/glvnd/egl_vendor.d/50_mesa.json

# 2) 恢复 Adreno 符号链接
cd /usr/lib/aarch64-linux-gnu
sudo ln -sfn libEGL.so.1.0.0      libEGL.so.1
sudo ln -sfn libGLESv2.so.2.0.0   libGLESv2.so.2

# 3) 恢复 AGNOS 原版 libgbm（注意：它的 SONAME 是 libgbm.so，所以 ldconfig 不会再抢）
sudo rm -f libgbm.so.1.0.0
sudo ln -sfn libgbm.so            libgbm.so.1

sudo ldconfig

# 4) 重启 magic 和 openpilot
sudo systemctl reset-failed magic
sudo systemctl restart magic
sudo systemctl restart comma.service
```

**验证成功的标志**：

```bash
systemctl is-active magic          # active
ls -S /tmp/drmfd.sock              # 存在（socket）
readlink -f /usr/lib/aarch64-linux-gnu/libEGL.so.1     # → libEGL_adreno.so
readlink -f /usr/lib/aarch64-linux-gnu/libgbm.so.1     # → libgbm.so
ps -eo cmd | grep selfdrive.ui.ui  # 有 UI 进程
```

> **教训**：在 AGNOS 上装编译依赖时，**用 `--no-install-recommends` 并逐个确认不会拉入 Mesa 的 EGL/GLES/GBM 包**。装完用 `readlink -f libEGL.so.1` 检查是否仍指向 Adreno。

### 参数文件属主问题（反复出现）

用 `sudo tar` 恢复参数备份会把文件变成 `root:root`，而 `comma.service` 以 `User=comma` 运行 → manager 读取失败 → **所有子进程都不启动**，但服务显示 `active`。

症状日志：
```
shutil.Error: [('/data/params/d/XXX', ..., "[Errno 13] Permission denied")]
```

修复：
```bash
sudo chown -R comma:comma /data/params
sudo find /data/params -type f -exec chmod 600 {} \;
sudo systemctl restart comma.service
```

---

## 十二、关键命令速查

```bash
# 当前槽 / 切槽
abctl --boot_slot
sudo abctl --set_active 0     # 槽 A
sudo abctl --set_active 1     # 槽 B

# 服务
sudo systemctl restart comma.service
systemctl is-active weston weston-ready

# 诊断 UI
ps -eo pid,etime,rss,cmd | grep '\./ui$'
grep -o 'UI WAYLAND EXIT: [^"]*' $(ls -t /data/log/swaglog.* | head -1) | tail -3
grep -o 'ui is dead with [^"]*'  $(ls -t /data/log/swaglog.* | head -1) | tail -3

# 背光
cat  /sys/class/backlight/panel0-backlight/brightness
echo 1023 | sudo tee /sys/class/backlight/panel0-backlight/brightness

# 根分区只读 → 可写
sudo mount -o rw,remount /
sudo bash /usr/comma/apt_teardown.sh   # 恢复只读
```
