# StarPilot C3X 汉化与定制补丁

> comma 3X 上 StarPilot 的**完整简体中文汉化** + 首页重构 + 通用别克威朗（BUICK_VERANO）支持。
> 以补丁形式分发，可一键安装、一键回滚，适配多台设备。

---

## 目录

- [适用设备与基线](#适用设备与基线)
- [快速安装](#快速安装)
- [包含内容](#包含内容)
- [功能说明](#功能说明)
- [安装脚本做了什么](#安装脚本做了什么)
- [回滚](#回滚)
- [日常维护](#日常维护)
- [故障排查](#故障排查)
- [已知限制](#已知限制)
- [九、9008 整机克隆](#九9008-整机克隆可选进阶)
- [变更记录](#变更记录)

---

## 适用设备与基线

| 项目 | 要求 |
|---|---|
| 硬件 | comma 3X（C3X） |
| 系统 | AGNOS 19.9（Ubuntu 24.04） |
| openpilot | 0.10.3 |
| 分支 | [StarPilotHQ/StarPilot@StarPilot](https://github.com/StarPilotHQ/StarPilot) |
| 基线 commit | `2589caad342a25f96412ef4027591387ffb06a4a` |
| UI 框架 | raylib（Python），非 Qt |

> ⚠️ 基线 commit 不一致时补丁可能无法干净应用。安装脚本会检测并提示，用 `--force` 可强制尝试。

**验证过的设备**：`comma-5e0dca10`（DongleId `sky_ef7kjnxxwdie`），AGNOS 19.9，slot `_a`。

---

## 快速安装

### 1. 推送发布包到 GitHub（只需做一次）

在**有 git 和 GitHub 凭据**的电脑上：

```bash
cd starpilot-c3x-zh
git init
git add -A
git commit -m "StarPilot C3X 汉化 v1.0.0"
git branch -M main
git remote add origin git@github.com:<你的用户名>/starpilot-c3x-zh.git
git push -u origin main
```

### 2. 在设备上安装

SSH 进设备（`ssh comma@<设备IP>`），然后：

```bash
cd /tmp
git clone https://github.com/<你的用户名>/starpilot-c3x-zh.git
cd starpilot-c3x-zh
sudo bash install.sh
```

装完会自动重启 `comma.service`。屏幕约 40 秒后恢复，界面即为中文。

### 3. 更新到新版本

```bash
cd /tmp/starpilot-c3x-zh
git pull
sudo bash install.sh --force
```

> `--force` 会让已应用过的补丁不报错重试，并覆盖投放文件。

### 离线安装（设备无外网）

在有网的电脑上下载 ZIP，通过 `scp` 传过去：

```bash
scp -i <你的密钥> -r starpilot-c3x-zh comma@192.168.1.12:/tmp/
ssh -i <你的密钥> comma@192.168.1.12 'sudo bash /tmp/starpilot-c3x-zh/install.sh'
```

---

## 包含内容

### 代码补丁（11 个）

| 文件 | 改动 | 目的 |
|---|---|---|
| `system/ui/lib/multilang.py` | +1 −1 | 修复语言代码解析，使非英文语言可被选中 |
| `system/ui/lib/application.py` | +3 −0 | 新增 `FontWeight.CJK` 与中文 CJK 字体回退 |
| `system/ui/widgets/label.py` | +10 −4 | `gui_text_box` 在文本含非 ASCII 时切 CJK 字体（修方块字）|
| `opendbc_repo/opendbc/car/gm/values.py` | +6 −0 | 新增 `BUICK_VERANO` 平台配置 |
| `opendbc_repo/opendbc/car/gm/fingerprints.py` | +16 −0 | 新增别克威朗 132 地址指纹（含 `0x2FF` SASCM）|
| `selfdrive/ui/layouts/settings/settings.py` | +2 −1 | 设置侧栏隐藏蓝牙面板 |
| `selfdrive/ui/layouts/home.py` | +60 −6 | 首页重构：双标签 + 移除实验模式横幅/配对卡片 |
| `selfdrive/ui/onroad/starpilot/favorite_radial_menu.py` | +19 −17 | 收藏菜单标题/描述/分区标签全部走 `tr()` |
| `selfdrive/ui/onroad/alert_renderer.py` | +2 −2 | 行车警报文本走 `tr()` |
| `selfdrive/ui/widgets/drive_stats.py` | +84 −11 | 统计仪表盘重写为原厂风格 |
| `selfdrive/assets/fonts/process.py` | +6 −3 | 字体字符集提取修复 |

### 新增/生成文件（5 个）

| 文件 | 大小 | 说明 |
|---|---|---|
| `selfdrive/ui/widgets/vehicle_status.py` | 11 KB | **车辆状态面板**（新功能）|
| `selfdrive/ui/translations/app_zh-CHS.po` | 226 KB | **2,119 条中文翻译** |
| `selfdrive/assets/fonts/NotoSansSC-Regular.fnt` | 127 KB | 字体图集描述（1,113 字形）|
| `selfdrive/assets/fonts/NotoSansSC-Regular.png` | 692 KB | 字体图集位图（2160×1512）|
| `build.json` | 382 B | 构建元数据（无 `.git` 的 tarball 必需）|

---

## 功能说明

### 一、完整汉化

覆盖范围：

| 层级 | 条目数 |
|---|---|
| 主界面 / 设置菜单 / 二级菜单 | 2,119 |
| 行车警报（含渲染器补丁）| 165 |
| 收藏动作（含渲染补丁）| 13 |
| 设置目录标签 | 376 / 376 |
| 设置目录描述 | 369 / 369 |
| 收藏选择器描述 | 191 / 191 |
| Galaxy 网页 | 内置中文（跟随设备语言自动切换）|

关键技术点：

1. **字体图集必须包含所有用到的字形**
   - raylib 用预烘焙 BMFont 图集，缺字会显示成方块/问号
   - 生成器从三个来源收集字符：`.po` 翻译、代码里的字符串字面量、固定标点集
   - 重新生成：`sudo /usr/local/venv/bin/python3 tools/make_cjk_font.py`

2. **`tr()` vs `trn()`**
   - `tr()` 查单数表；`trn()` 查 `msgid_plural` 复数表
   - 复数条目必须写成 `msgid` + `msgid_plural` + `msgstr[0]`/`msgstr[1]`

3. **`gui_text_box` 的字体陷阱**
   - 原实现在 `FontWeight.NORMAL` 时使用 raylib 内置拉丁字体，中文变方块
   - 已修补：文本含非 ASCII 字符时自动切 CJK 字体

4. **渲染时才翻译的字符串**
   - 很多文案存在 JSON（`device_settings_layout.json`）或字典字面量里，AST 扫描扫不到
   - 必须在渲染处包 `tr()`：`tr(str(option.get("label")))`

### 二、首页重构

原版首页是 StarPilot 的「Regret Driven Framework V4」样式，改为原厂 0.11.x 风格：

```
┌─────────────┬─────────────┬─────────────┐
│  累计行程    │ 辅助驾驶时长 │   总里程     │
│   89 次     │ 7 小时 53 分 │  148.6 km   │
│ 平均 5 分钟/次│ 累计上路时长  │ 本机累计行驶距离│
└─────────────┴─────────────┴─────────────┘
┌───────────────────────────────────────┐
│ 最近行程                                 │
│ 第4次 · 11-17 13:42      0.9 km · 3 分钟 │
│ 第3次 · 11-17 13:34      0.7 km · 4 分钟 │
│ …                                      │
│ ─────────────────────────────────────  │
│ 当前模型                    Pop Model V2 │
│ 软件版本                       0.10.3    │
└───────────────────────────────────────┘
```

- 行程编号**从 0 开始按时间累加**（最早一次 = 第 0 次）
- 移除了原右侧的「实验模式已开启」横幅与「完成设置/配对设备」卡片
- 顶部增加 **行驶统计 / 车辆状态** 双标签

### 三、车辆状态面板（新功能）

切到「车辆状态」标签显示：

**第一行 4 个小卡**

| 卡片 | 数据来源 | 颜色阈值 |
|---|---|---|
| 运存占用 | `/proc/meminfo` | >75% 黄，>90% 红 |
| CPU 温度 | `/sys/class/thermal/thermal_zone*` | >70 黄，>80 红 |
| 可用存储 | `/data` 分区 | <12% 黄，<5% 红 |
| 网络连接 | `wlan0`/`eth0` + IP | — |

**第二行 3 个状态卡（带彩色圆点）**

| 卡片 | 判定逻辑 |
|---|---|
| 车辆 | `carParams.carFingerprint`（如 `BUICK_VERANO`）|
| SASCM | `carParams.flags & GMFlags.SASCM`（=32）。**仅设备启动做指纹时检测一次**，运行中不重复检测。显示「可用」/「不可用」|
| 毫米波雷达 | 检测原车雷达目标 ID（`liveTracks.points.trackId`），保留 60 秒记忆避免空旷路段误判。显示「可用」/「不可用」|

> 按需求**不显示**：纵向控制、Panda、原车视觉。
>
> SASCM 的 `0x2FF` 心跳机制参考：
> - https://github.com/garrettpall/SASCM
> - https://github.com/garrettpall/ocelot/tree/sascm

### 四、别克威朗（BUICK_VERANO）支持

在 `values.py` 新增平台配置：

```python
BUICK_VERANO = GMSDGMPlatformConfig(
  [GMCarDocs("Buick Verano 2018", "ACC & LKAS")],
  GMCarSpecs(mass=1320, wheelbase=2.70, steerRatio=16.0, centerToFrontRatio=0.4),
)
```

在 `fingerprints.py` 新增 **132 地址指纹**（含 `767: 4` = `0x2FF` SASCM 心跳），并加入 `SDGM_CAR` 列表。

选车路径：`设置 › 车辆 › 汽车型号` → 品牌选 **Buick** → 型号选 **Buick Verano 2018**。

> ⚠️ `steerRatio=16.0` 是估算值，实车如出现转向打满/不足请微调。
> ⚠️ 纵向控制需另行验证，实验模式下的红绿灯制动**仅为辅助**。

---

## 安装脚本做了什么

按顺序执行 7 步：

1. **环境检查** —— 确认 `/data/openpilot` 存在、`manifest.json` 完整、以 root 运行
2. **备份** —— 所有将被修改的文件复制到 `/data/openpilot/.zh_backup_<时间戳>/`
3. **应用补丁** —— 逐个 `patch -p1`，先 `--dry-run` 探测；已应用过的自动跳过
4. **投放文件** —— 复制新文件与生成物（`.po`、字体图集、`vehicle_status.py`、`build.json`）
5. **权限修正** —— `chown -R comma:comma`
6. **清缓存** —— 删除所有 `__pycache__`
7. **设置语言 + 重启** —— `LanguageSetting=main_zh-CHS`，重启 `comma.service`

### 参数

| 参数 | 作用 |
|---|---|
| `--force` | 补丁冲突时强制尝试；重复安装不报错 |
| `--no-restart` | 安装后不重启服务 |
| `-h` / `--help` | 帮助 |

---

## 回滚

安装时创建的备份目录可以完整还原：

```bash
sudo bash uninstall.sh /data/openpilot/.zh_backup_20261118-001234
```

不传参数则自动用最新备份：

```bash
sudo bash uninstall.sh
```

回滚会恢复所有被修改的文件并重启服务。

> 语言设置 `LanguageSetting` **不会**被回滚（因为它是新写入的）。需要改回去就用设置界面改。

---

## 日常维护

### 修改翻译

1. 编辑 `files/selfdrive/ui/translations/app_zh-CHS.po`（`.po` 是纯文本，运行时解析，无需编译）
2. 部署到设备：
   ```bash
   scp app_zh-CHS.po comma@192.168.1.12:/tmp/
   ssh comma@192.168.1.12 'sudo cp /tmp/app_zh-CHS.po /data/openpilot/selfdrive/ui/translations/ && sudo systemctl restart comma.service'
   ```
3. 如果新增了**之前没出现过的汉字**，必须重新生成字体图集（否则显示方块）

### 重新生成字体图集

```bash
sudo /usr/local/venv/bin/python3 /path/to/tools/make_cjk_font.py
```

依赖：

- `/usr/share/fonts/NotoSansSC-Regular.otf`（AGNOS 自带）
- Pillow（`/usr/local/venv` 里已装）

脚本会扫描 `selfdrive/ui`、`starpilot`、`system/ui` 下所有 `.py` 的字符串字面量，收集 CJK 字符。

> ⚠️ **不要用 `selfdrive/assets/fonts/process.py`**：raylib 的 `gen_image_font_atlas` 处理 NotoSansSC OTF 会崩溃或产出 16384×16384 的超大图集。

### 检查复数条目

```bash
/usr/local/venv/bin/python3 tools/audit_trn.py
```

扫描全部 `trn()` 调用，报告缺少 `msgid_plural` 的条目。

### 验证翻译是否生效

```bash
/usr/local/venv/bin/python3 -c "
import sys, pathlib; sys.path.insert(0,'/data/openpilot')
from openpilot.system.ui.lib.multilang import load_translations
tr, pl = load_translations(pathlib.Path('/data/openpilot/selfdrive/ui/translations/app_zh-CHS.po'))
print(len(tr), '条')
print(tr.get('Lane Centering'))
"
```

---

## 故障排查

### 界面全是方块/问号

字体图集缺字。重新生成：

```bash
sudo /usr/local/venv/bin/python3 /path/to/tools/make_cjk_font.py
sudo systemctl restart comma.service
```

### 界面还是英文

1. 检查语言设置：`cat /data/params/d/LanguageSetting` 应为 `main_zh-CHS`
2. 检查 `.po` 是否装上：`grep -c '^msgid ' /data/openpilot/selfdrive/ui/translations/app_zh-CHS.po`
3. 检查 `.po` 语法（多余引号会让整个文件解析失败）

### 某项文案没翻译

大概率是**渲染时才翻译**的字符串。在渲染处包 `tr()`：

```python
title = tr(str(option.get("label") or ""))
```

改完重启服务即可。

### UI 崩溃 / 黑屏

```bash
sudo systemctl status comma.service
journalctl -u comma -n 100
```

或手动前台运行看堆栈：

```bash
sudo systemctl stop comma.service
cd /data/openpilot
/usr/local/venv/bin/python3 -m openpilot.selfdrive.ui.ui
```

### 补丁应用失败

```
error: patch failed: xxx.py:123
```

说明基线 commit 不一致或该文件已被改动。先回滚，确认基线后再装：

```bash
sudo bash uninstall.sh
cat /data/openpilot/build.json    # 看 git_commit
```

### 屏幕无法点亮（AGNOS 图形栈）

AGNOS 的显示由 `magic.py` 持有 DRM master，通过 `/tmp/drmfd.sock` 把 fd 传给客户端。排查：

```bash
systemctl status magic
ls -la /usr/lib/aarch64-linux-gnu/libEGL.so.1   # 应指向 libEGL_adreno
```

⚠️ **不要把 Mesa 的 `libEGL.so.1` 装上**，会覆盖 Adreno 导致 magic 启动失败、屏幕全黑。

---

## 已知限制

1. **`build.json` 是必需的** —— 补丁树来自 tarball，没有 `.git`，缺这个文件会报 `invalid build metadata`
2. **`magic.service` 在 stock AGNOS 16 上永久失败** —— 会多约 20 秒启动时间（仅影响 slot B）
3. **触摸问题（slot B / AGNOS 16）** —— weston 是 32 位且 libinput 未创建输入设备，触摸不可用；slot A（AGNOS 19.9）正常
4. **别在开机时触摸屏幕** —— `comma.sh` 检测到 `touch_count > 4` 会触发恢复出厂，`/data` 会被清空
5. **`steerRatio=16.0` 未实车标定** —— 威朗的转向比是估算值
6. **纵向控制未实车验证** —— 红绿灯/ACC 制动仅为辅助功能
7. **上游缺失的指纹** —— `BUICK_LACROSSE_ASCM_19US` 和 `CHEVROLET_TRAILBLAZER` 上游本身没有指纹

---

## 九、9008 整机克隆（可选，进阶）

把一整台 C3X 做成 9008 可刷包，用于**变砖恢复**或**多设备统一部署**。

> **详细步骤、实测数据和踩坑记录见 [`docs/9008打包与刷写指南.md`](docs/9008打包与刷写指南.md)。**
> 本章只给结论和最短路径。

### 关键结论

| 项目 | 结论 |
|---|---|
| 能否做包 | ✅ 84 项 / 29.13 GiB，通过工具自身校验 |
| **推荐导出方式** | **SSH + dd**（18-19 MB/s，约 27 分钟）|
| 不要用 | EDL/Firehose 读取（1.4 MB/s 且频繁停顿，实测 5 次全失败）|
| 实机刷写验证 | ❌ 未做，首次用可放弃的设备 |
| 身份问题 | ⚠️ 含来源设备校准/IMEI/TEE 密钥，仅限自有设备间克隆 |

### 最短路径

```powershell
# 1. 设备正常开机（不是 9008），能 SSH
# 2. 探测分区表（只读，30 秒）
python tools\build_package_ssh.py --ssh comma@192.168.1.12 \
    --ssh-key "$env:USERPROFILE\.ssh\id_ed25519_comma" \
    --out D:\c3x_pkg --flasher-source "D:\SkyGMFlasher\source" \
    --firehose-from "D:\已有包" --dry-run

# 3. 正式导出（约 27 分钟）
python tools\build_package_ssh.py --ssh comma@192.168.1.12 \
    --ssh-key "$env:USERPROFILE\.ssh\id_ed25519_comma" \
    --out D:\c3x_pkg --flasher-source "D:\SkyGMFlasher\source" \
    --firehose-from "D:\已有包" --split-mb 0 --yes

# 4. 若校验报错，用修复工具补全
python tools\repair_package.py
```

导出完成后用 SkyGMFlasher：选包 → 连接 → **全选 84 项** → **勾选重建分区表** → 刷写。

刷完首启会自动重建 `/data`（64 KiB 标记触发 `reset --recover`），然后：

```bash
scp -r starpilot-c3x-zh comma@<设备IP>:/tmp/
ssh comma@<设备IP> 'sudo bash /tmp/starpilot-c3x-zh/provision.sh'
```

### 工具链

| 脚本 | 用途 |
|---|---|
| `tools/build_package_ssh.py` | **推荐**。SSH + dd 导出 |
| `tools/build_package.py` | EDL/Firehose 导出（大分区会超时，仅供调试/小包）|
| `tools/repair_package.py` | 修复清单：补 userdata / 修哈希 / 登记 Firehose |

---

## 变更记录

### v1.4.2 — 2026-11-19

修正 v1.4.1 的一个严重错误，并把启动提示改为中文。

**v1.4.1 的错误**

静止守卫写成了 `self.sm['carState'].vEgo`，但 `selfdrived` 的 SubMaster 里
**没有 `carState`** —— 它用的是独立 socket：

```python
self.car_state_sock = messaging.sub_sock('carState', timeout=20)
...
CS = self.data_sample()          # ← update_events(self, CS) 的 CS 参数
```

结果每帧抛 `KeyError` → `selfdrived` 崩溃重启 → **启动提示反复弹出**
（用户看到的「Hop in and buckle up! 一直跳」就是这个崩溃循环的外在表现）。

**修正**：改用 `update_events` 的 `CS` 参数。

```python
parked = CS.vEgo < 0.1
if not all_checks and report_comm_issue and ... and not parked:
```

**验证**：`selfdrived` 运行时长稳定增长（45s → 60s → 75s，无重启），
`alertType` 为空。

**启动提示改中文**

`StartupMessageTop` / `StartupMessageBottom` 是 StarPilot 的自定义启动提示
（原车主设成了 "Hop in and buckle up!" / "Human-tested, frog-approved 🐸"），
在接合时显示 5 秒。现改为：

| 参数 | 值 |
|---|---|
| `StartupMessageTop` | 请随时准备接管车辆 |
| `StartupMessageBottom` | 保持双手在方向盘上并注视道路 |

字体图集已覆盖全部字符（6,933 字）。

### v1.4.1 — 2026-11-19

修复「停车不启动发动机时显示进程间通信异常」。

**现象**：车辆停在原地、发动机未启动（点火开关在 ON/ACC 档）时，屏幕持续显示
`Communication Issue Between Processes`。

**排查过程**

1. 复刻 `selfdrived` 的 SubMaster 订阅列表，逐条统计 `valid` 状态，发现 6 个消息
   100% 无效：
   ```
   longitudinalPlan  liveDelay  liveParameters
   radarState      liveTorqueParameters  driverAssistance
   ```
2. 追到两个独立根因：
   - **`radarState.valid`** ← `radard.py:628` 的 `sm.all_checks()`。radard 订阅了
     `liveTracks`（要求 20 Hz），但熄火时雷达不供电，实际只有 6.7 Hz →
     `freq_ok=False`。而 `has_slow_radar_tracks()` 因为
     `radarTimeStepDEPRECATED=0.0667 < 2/20=0.1` 返回 False，没有忽略频率检查。
   - **`liveParameters.valid`** ← `paramsd.py:188` 要求 6 个条件全满足，其中
     `roll_valid` 依赖滤波器 roll 标准差。**车辆静止时没有发动机振动，IMU 噪声
     特性改变，`roll_std` 漂移超出阈值** → `valid=False`。
3. `plannerd.py:39` 的 `longitudinalPlan.valid = sm.all_checks([...,'liveParameters'])`
   把 `liveParameters` 的失效传染给纵向规划，最终 `all_checks()=False` → `commIssue`。

**修复**

`selfdrive/selfdrived/selfdrived.py`：车辆静止时跳过 `commIssue` 上报。

```python
parked = self.sm['carState'].vEgo < 0.1
if not all_checks and report_comm_issue and ... and not parked:
    if not all_alive:
        self.events.add(EventName.commIssue)
```

**安全性**：`commIssue` 的语义是**禁止接合**（NO_ENTRY）。车辆静止时本来就不会接合，
跳过上报无安全影响；**行驶中该检查完整保留**，任何真实的进程通信故障仍会正常报警。

**验证**：熄火状态下采样 20 秒，`alertType` 为空（告警消失）。

### v1.4.0 — 2026-11-19

别克威朗纵向控制「低速刹停」完整修复。

**问题现象**：高速跟车正常，但低速跟车减速刹停、红灯刹停全部失效，车辆卡在 4.5 km/h 蠕行。

**诊断方法**：在车上采集 17,808 帧实时数据（`/data/brake_diag2.csv`），同时记录
`carControl.actuators`、`carState.aEgo`、`longControlState` 以及 `0x315`
（`EBCMFrictionBrakeCmd`）报文的原始字节，用 DBC 精确解码 `FrictionBrakeCmd`
和 `FrictionBrakeMode`。

**定位到的三个问题**

1. **停车参数太弱**（`interface.py` 威朗专用分支）
   ```python
   ret.stoppingDecelRate = 1.0    → 3
   ret.vEgoStopping     = 0.25   → 0.75
   ret.vEgoStarting     = 0.25   → 0.75
   ret.stopAccel        = -0.25  → -1.5
   ```
   `stopAccel=-0.25` 只产生 `25/400`（6%）的刹车量，对抗不了自动挡怠速蠕行。
   改成 `-1.5` 后是 `150/400`（38%）。

2. **红灯减速开关被关闭**
   `CEStopLights = 0`（出厂默认 1）→ 恢复为 1。

3. **静止前车不响应**
   `CEStoppedLead = 0` → 开启为 1，让「前车静止 <1 m/s 且距离 <40 m」触发条件实验模式。

**验证结果**

| 指标 | 修复前 | 修复后 |
|---|---|---|
| `longControlState=stopping` 帧 | 0 | 2,835 |
| `standstill` 帧 | 0 | 2,874 |
| 最低车速 | 4.5 km/h（卡死）| 0.0 km/h |
| 最长连续静止 | 0 秒 | **28.7 秒** |

停车时 `0x315` 发出 `FrictionBrakeCmd=150`、`FrictionBrakeMode=0xd`（驻车保持），
`drvBrake=0`（驾驶员零介入）。

**⚠️ 使用注意**

实测发现 **EBCM 有驾驶员优先权**：只要脚搭在刹车踏板上（哪怕只有 4-5%），它就会忽略
SASCM 转发来的刹车指令。想让 openpilot 自己刹停，右脚必须完全离开刹车踏板。

**install.sh 现在自动设置的参数**

| 参数 | 值 | 作用 |
|---|---|---|
| `AlphaLongitudinalEnabled` | 1 | 启用 openpilot 纵向控制 |
| `ClusterOffset` | 1.19 | UI 车速显示校准 |
| `CEStopLights` | 1 | 红灯减速 |
| `CEStoppedLead` | 1 | 静止前车响应 |

**顺带澄清的两个误判**（避免以后重复排查）

- ❌ 不是 panda 拦截 bus2 上的 `0x315`：`GM_CAM_LONG_TX_MSGS` 里明确允许
  `{0x315, 2, 5, .check_relay=false}`。
- ❌ 不是刹车总线选错：`get_friction_brake_bus()` 返回 `CanBus.CAMERA` 是对的，
  符合「C3X 经摄像头总线 → SASCM 转发 → EBCM」的实际架构。

### v1.3.0 — 2026-11-18

别克威朗（BUICK_VERANO）实车适配：从「能识别」到「能开」。

**新修复**

- **雷达左右镜像**：`radar_interface.py` 增加 `AZIMUTH_SIGN` 表，仅对威朗把
  `TrkAzimuth` 取反。之前左侧车道的车会显示在右侧，导致视觉-雷达融合始终
  匹配失败（`radard.track_matches_vision` 的 `lat_sane` 过不了）。
- **纵向控制启用**：SDGM 线束替换了原车 SDGM 模块，原厂 ACC 链路已断，
  必须设 `AlphaLongitudinalEnabled=1` 让 openpilot 通过 SASCM 提供纵向。
  否则 `pcmCruise=True` 会让 openpilot 空等一个不存在的原厂 ACC，
  表现为「按 SET 立即退出」。
- **接合速度设为 0**：`minEnableSpeed=0`，任意速度可接合。
- **转向提示按实测校准**：威朗 EPS 在 10-45 km/h 有 65-68% 的帧报
  `LKATorqueDeliveredStatus=2`（扭矩限制），45-50 km/h 降至 1.6%，
  50 km/h 以上为 0%。5 万帧实测数据见表。50 km/h 以下属该车型正常特性，
  不再误报「转向辅助不可用」；50 km/h 以上出现才告警。
- **地图道路名乱码**：字体图集从 1,113 字扩到 **6,933 字（GB2312 全表）**。
  地图道路名是运行时数据，不可能从 `.po` 或代码字面量里收集，必须覆盖常用汉字全表。
- **恢复出厂保护**：`comma.sh` 的「触摸计数 >4 即恢复出厂」改为 opt-in
  （需 `/data/.allow_tap_reset`）。`touch_count` 是内核累计计数、跨重启不清零，
  实测中曾误触发工厂重置（已及时终止，数据无损）。

**新增参数（install.sh 自动设置）**

| 参数 | 值 | 作用 |
|---|---|---|
| `AlphaLongitudinalEnabled` | `1` | 启用 openpilot 纵向控制 |
| `ClusterOffset` | `1.19` | UI 车速显示校准（只影响显示） |

**新增工具**

- `tools/eps_speed_test.py`：实测 EPS 拒绝转向扭矩的速度阈值，按 5 km/h 分档
  统计 `LKATorqueDeliveredStatus=2` 占比，输出 CSV + 分档表。
- `tools/capture_steer_hi.py`：只在行驶时记录转向状态变化，用于现场排障。

### v1.2.1 — 2026-11-18

修复威朗上车后 `card` 崩溃。

- **新增 `patch/substitute.toml.patch`**：`opendbc/car/torque_data/substitute.toml` 里缺少 `BUICK_VERANO`
  → `get_torque_params()[candidate]` KeyError → `card` 进程崩溃 → 界面显示「openpilot 无法使用」
- 该文件用「替代车型」机制映射扭矩参数，所有别克都指向 `CHEVROLET_VOLT`，威朗漏了
- 实车验证：补上后 `carFingerprint = BUICK_VERANO`，`card` 稳定运行

> ⚠️ v1.2.0 及更早的包在威朗上会出现这个问题，请务必更新到 v1.2.1。

### v1.2.0 — 2026-11-18

9008 整机克隆落地：从设备成功导出并校验通过完整刷机包。

- 新增 `tools/build_package_ssh.py`：**SSH + dd 导出**，18-19 MB/s，实测 27 分钟导出 29.13 GiB
- 新增 `tools/repair_package.py`：修复清单（补 userdata / 重算哈希 / 登记 Firehose）
- 新增 `docs/9008打包与刷写指南.md`：完整流程 + 7 个踩坑记录 + 实测数据
- `tools/build_package.py`（EDL 版）：修复 GPT 修复函数误用、XML 类型、零填充分块
- 结论：EDL 读取不可用于大包（1.4 MB/s + 频繁停顿 + 重试污染协议），SSH 是唯一可行路径

### v1.1.0 — 2026-11-18

新增 9008 整机克隆能力。

- 新增 `provision.sh`：刷机后一键部署（clone → 依赖 → continue.sh → 参数 → 汉化补丁 → 验证）
- 新增 `tools/build_package.py`：从 9008 设备导出自建刷机包，支持 `--dry-run` / `--verify-only` / 分区切分 / 零填充
- 完成第三方 RC10 包的完整可行性验证（Firehose 哈希、83 项清单、6 LUN 容量）
- 文档新增第九章「9008 整机克隆」

### v1.0.0 — 2026-11-18

首发版本。

- 完整简体中文汉化（2,119 条）
- CJK 字体图集（1,113 字形，含中英混排标点）
- 修复 `gui_text_box` 中文方块问题
- 修复 `multilang.py` 语言代码解析 bug
- 首页重构（三卡 + 最近行程 + 底部版本）
- 新增车辆状态面板（行驶统计/车辆状态双标签）
- 新增别克威朗 `BUICK_VERANO` 支持
- 设置侧栏隐藏蓝牙面板
- 收藏菜单、行车警报全部汉化

---

## 目录结构

```
starpilot-c3x-zh/
├── README.md                 # 本文档
├── VERSION                   # 版本号
├── manifest.json             # 文件清单 + SHA256 + 基线信息
├── install.sh                # 汉化补丁安装脚本
├── uninstall.sh              # 回滚脚本
├── provision.sh              # 刷机后一键部署（StarPilot + 汉化）
├── patch/                    # 15 个 unified diff 补丁
│   ├── multilang.py.patch
│   ├── application.py.patch
│   ├── label.py.patch
│   ├── values.py.patch
│   ├── fingerprints.py.patch
│   ├── settings.py.patch
│   ├── home.py.patch
│   ├── favorite_radial_menu.py.patch
│   ├── alert_renderer.py.patch
│   ├── drive_stats.py.patch
│   └── process.py.patch
├── files/                    # 需原样投放的文件
│   ├── build.json
│   └── selfdrive/
│       ├── ui/widgets/vehicle_status.py
│       ├── ui/translations/app_zh-CHS.po
│       └── assets/fonts/NotoSansSC-Regular.{fnt,png}
├── tools/                    # 维护与构建工具
│   ├── make_cjk_font.py      # 字体图集生成器
│   ├── audit_trn.py          # 复数条目审计
│   ├── build_package.py      # 9008 包导出（EDL 版，仅供调试）
│   ├── build_package_ssh.py  # 9008 包导出（SSH 版，推荐）
│   └── repair_package.py     # 清单修复工具
└── docs/                     # 相关文档
    ├── C3X_StarPilot_部署实录.md
    ├── 9008刷机可行性验证报告.md
    └── 9008打包与刷写指南.md
```

---

## 许可与致谢

- 基线：[StarPilotHQ/StarPilot](https://github.com/StarPilotHQ/StarPilot)（MIT）
- 车系：[commaai/opendbc](https://github.com/commaai/opendbc)（MIT）
- SASCM 参考：[garrettpall/SASCM](https://github.com/garrettpall/SASCM)、[garrettpall/ocelot](https://github.com/garrettpall/ocelot/tree/sascm)
- 字体：Noto Sans SC（SIL Open Font License 1.1）

本补丁包仅为适配性修改，请自行评估行车安全风险。
