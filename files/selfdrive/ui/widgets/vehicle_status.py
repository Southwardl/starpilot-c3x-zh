"""车辆状态面板：运存 / CPU 温度 / 存储 / 网络 + 车辆 / SASCM / 雷达。
参考原厂 0.11.x 首页风格；不含纵向控制、Panda、原车视觉三项。
"""
from __future__ import annotations

import shutil
import socket
import time
import traceback
from pathlib import Path
from typing import Any

import pyray as rl

from openpilot.system.ui.lib.application import FontWeight, gui_app
from openpilot.system.ui.lib.multilang import tr
from openpilot.system.ui.lib.text_measure import measure_text_cached

CARD_COLOR = rl.Color(18, 20, 29, 255)
CARD_BORDER = rl.Color(67, 57, 86, 255)
TEXT_COLOR = rl.Color(250, 248, 255, 255)
MUTED_COLOR = rl.Color(190, 186, 207, 255)
GREEN = rl.Color(64, 214, 128, 255)
RED = rl.Color(232, 76, 76, 255)
AMBER = rl.Color(232, 176, 64, 255)
PURPLE = rl.Color(139, 108, 197, 255)
TEAL = rl.Color(94, 200, 200, 255)

REFRESH_S = 2.0
RADAR_MEMORY_S = 60.0


# ---------------- 数据读取 ----------------

def _read_meminfo() -> tuple[float, float, float]:
    """返回 (已用 GB, 总 GB, 已用百分比)。"""
    try:
        info: dict[str, int] = {}
        for line in Path("/proc/meminfo").read_text().splitlines():
            parts = line.split(":")
            if len(parts) == 2:
                info[parts[0].strip()] = int(parts[1].split()[0])
        total = info.get("MemTotal", 0) / 1024.0 / 1024.0
        avail = info.get("MemAvailable", info.get("MemFree", 0)) / 1024.0 / 1024.0
        used = max(0.0, total - avail)
        pct = (used / total * 100.0) if total else 0.0
        return used, total, pct
    except Exception:
        return 0.0, 0.0, 0.0


def _read_cpu_temp() -> float:
    """CPU 温度（摄氏度），取所有 thermal_zone 的最大合理值。"""
    best = 0.0
    for zone in Path("/sys/class/thermal").glob("thermal_zone*"):
        try:
            raw = int((zone / "temp").read_text().strip())
        except Exception:
            continue
        celsius = raw / 1000.0 if raw > 1000 else float(raw)
        if 0 < celsius < 150:
            best = max(best, celsius)
    return best


def _read_storage() -> tuple[float, float, float]:
    """返回 (/data 可用 GB, 总 GB, 可用百分比)。"""
    try:
        usage = shutil.disk_usage("/data")
        total = usage.total / 1e9
        free = usage.free / 1e9
        pct = (free / total * 100.0) if total else 0.0
        return free, total, pct
    except Exception:
        return 0.0, 0.0, 0.0


def _network_text() -> tuple[str, str]:
    """返回 (网络类型, IP)。"""
    try:
        for iface, label in (("wlan0", "无线"), ("eth0", "有线")):
            if not Path(f"/sys/class/net/{iface}").exists():
                continue
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            try:
                s.settimeout(0.3)
                s.connect(("192.168.1.1", 80))
                ip = s.getsockname()[0]
            finally:
                s.close()
            if ip and not ip.startswith("127."):
                return tr(label), ip
        return tr("离线"), "-"
    except Exception:
        return tr("离线"), "-"


class VehicleStatusPanel:
    """车辆状态面板。"""

    def __init__(self, params: Any):
        self._params = params
        self._font_bold = gui_app.font(FontWeight.BOLD)
        self._font_semi_bold = gui_app.font(FontWeight.SEMI_BOLD)
        self._font_medium = gui_app.font(FontWeight.MEDIUM)
        self._last = 0.0
        self._cache: dict[str, Any] = {}
        self._radar_last_seen = 0.0
        self._radar_last_count = 0
        self.refresh(force=True)

    # ---------------- 数据 ----------------

    def refresh(self, force: bool = False) -> None:
        try:
            self._refresh_impl(force)
        except Exception:
            traceback.print_exc()

    def _refresh_impl(self, force: bool = False) -> None:
        now = time.monotonic()
        if not force and now - self._last < REFRESH_S:
            return
        self._last = now

        used, total, mem_pct = _read_meminfo()
        free, sto_total, sto_pct = _read_storage()
        net_kind, net_ip = _network_text()
        self._cache = {
            "mem_used": used, "mem_total": total, "mem_pct": mem_pct,
            "temp": _read_cpu_temp(),
            "sto_free": free, "sto_total": sto_total, "sto_pct": sto_pct,
            "net_kind": net_kind, "net_ip": net_ip,
            "car": self._car_name(),
            "sascm": self._sascm_state(),
            "radar": self._radar_state(),
        }

    def _car_name(self) -> str:
        try:
            from openpilot.selfdrive.ui.ui_state import ui_state
            cp = ui_state.sm["carParams"]
            if cp:
                name = str(cp.carFingerprint or "")
                return name or "-"
        except Exception:
            pass
        return "-"

    def _sascm_state(self) -> tuple[bool, str]:
        """SASCM 是否可用。

        仅在设备启动做车辆指纹时检测一次：指纹里出现 0x2FF 即置 GMFlags.SASCM。
        运行中不重复检测，符合「启动时检测」的要求。
        """
        try:
            from openpilot.selfdrive.ui.ui_state import ui_state
            cp = ui_state.sm["carParams"]
            flags = int(cp.flags or 0) if cp else 0
            try:
                from opendbc.car.gm.values import GMFlags
                sascm_bit = int(GMFlags.SASCM.value)
            except Exception:
                sascm_bit = 1 << 5
            connected = bool(flags & sascm_bit)
            return connected, tr("可用") if connected else tr("不可用")
        except Exception:
            return False, tr("不可用")

    def _radar_state(self) -> tuple[bool, str]:
        """毫米波雷达可用性。

        依据：能否收到原车雷达目标 ID（liveTracks.points 里的 trackId）。
        目标短暂消失时保留 60 秒记忆，避免空旷路段误判为不可用。
        """
        try:
            from openpilot.selfdrive.ui.ui_state import ui_state
            cp = ui_state.sm["carParams"]
            if cp and bool(cp.radarUnavailable):
                return False, tr("不可用")
            count = 0
            try:
                tracks = ui_state.sm["liveTracks"]
                if tracks is not None:
                    count = sum(1 for p in tracks.points if int(p.trackId) >= 0)
            except Exception:
                count = 0
            now = time.monotonic()
            if count > 0:
                self._radar_last_seen = now
                self._radar_last_count = count
            if now - self._radar_last_seen < RADAR_MEMORY_S:
                return True, tr("可用")
            return False, tr("不可用")
        except Exception:
            return False, tr("不可用")

    # ---------------- 绘制 ----------------

    @staticmethod
    def _card(rect: rl.Rectangle, accent: rl.Color | None = None) -> None:
        rl.draw_rectangle_rounded(rect, 0.05, 10, CARD_COLOR)
        rl.draw_rectangle_rounded_lines_ex(rect, 0.05, 10, 2, CARD_BORDER)
        if accent is not None:
            bar_h = max(8.0, min(56.0, rect.height - 28.0))
            rl.draw_rectangle_rounded(
                rl.Rectangle(rect.x + 16, rect.y + 14, 5, bar_h), 1.0, 6, accent)

    def _stat_card(self, rect: rl.Rectangle, title: str, value: str, sub: str, accent: rl.Color) -> None:
        self._card(rect, accent)
        rl.draw_text_ex(self._font_medium, title, rl.Vector2(rect.x + 34, rect.y + 16), 24, 0, MUTED_COLOR)
        rl.draw_text_ex(self._font_bold, value, rl.Vector2(rect.x + 34, rect.y + 50), 44, 0, TEXT_COLOR)
        if sub:
            rl.draw_text_ex(self._font_medium, sub, rl.Vector2(rect.x + 34, rect.y + 108), 22, 0, MUTED_COLOR)

    def _status_card(self, rect: rl.Rectangle, title: str, value: str, sub: str,
                     dot: rl.Color | None) -> None:
        self._card(rect)
        x = rect.x + 28
        if dot is not None:
            rl.draw_circle(int(x + 6), int(rect.y + 30), 7, dot)
            x += 26
        rl.draw_text_ex(self._font_medium, title, rl.Vector2(x, rect.y + 18), 26, 0, MUTED_COLOR)
        rl.draw_text_ex(self._font_bold, value, rl.Vector2(rect.x + 28, rect.y + 62), 40, 0, TEXT_COLOR)
        if sub:
            rl.draw_text_ex(self._font_medium, sub,
                            rl.Vector2(rect.x + 28, rect.y + rect.height - 46), 22, 0, MUTED_COLOR)

    def render(self, rect: rl.Rectangle) -> None:
        # 渲染异常不允许打断 UI 主循环
        try:
            self._render_impl(rect)
        except Exception:
            traceback.print_exc()
            try:
                from openpilot.common.swaglog import cloudlog
                cloudlog.exception("[vehicle_status] render failed")
            except Exception:
                pass

    def _render_impl(self, rect: rl.Rectangle) -> None:
        self.refresh()
        c = self._cache

        gap = 16
        top_h = 132
        mid_h = 160

        # ---- 第一行：4 个小卡 ----
        n_top = 4
        top_w = max(120.0, (rect.width - (n_top - 1) * gap) / n_top)
        mem_pct = float(c.get("mem_pct", 0.0))
        temp = float(c.get("temp", 0.0))
        sto_pct = float(c.get("sto_pct", 0.0))
        mem_color = RED if mem_pct > 90 else (AMBER if mem_pct > 75 else TEAL)
        temp_color = RED if temp > 80 else (AMBER if temp > 70 else GREEN)
        sto_color = RED if sto_pct < 5 else (AMBER if sto_pct < 12 else TEAL)

        top_cards = (
            (tr("运存占用"), f"{mem_pct:.0f}%",
             tr("可用 {} / {}").format(f"{float(c.get('mem_total', 0.0)) - float(c.get('mem_used', 0.0)):.1f} GB",
                                       f"{float(c.get('mem_total', 0.0)):.1f} GB"), mem_color),
            (tr("CPU 温度"), f"{temp:.0f}°C", tr("热区最高值"), temp_color),
            (tr("可用存储"), f"{sto_pct:.0f}%",
             tr("可用 {} / {}").format(f"{float(c.get('sto_free', 0.0)):.1f} GB",
                                       f"{float(c.get('sto_total', 0.0)):.1f} GB"), sto_color),
            (tr("网络连接"), str(c.get("net_kind", "-")),
             tr("设备 IP {}").format(str(c.get("net_ip", "-"))), PURPLE),
        )
        for i, (title, value, sub, accent) in enumerate(top_cards):
            r = rl.Rectangle(rect.x + i * (top_w + gap), rect.y, top_w, top_h)
            self._stat_card(r, title, value, sub, accent)

        # ---- 第二行：3 张状态卡 ----
        n_mid = 3
        mid_w = max(160.0, (rect.width - (n_mid - 1) * gap) / n_mid)
        y2 = rect.y + top_h + gap
        sascm_ok, sascm_text = c.get("sascm", (False, tr("不可用")))
        radar_ok, radar_text = c.get("radar", (False, tr("不可用")))
        car_name = str(c.get("car", "-"))
        mid_cards = (
            (tr("车辆"), car_name, tr("车辆识别结果"), GREEN if car_name not in ("-", "") else RED),
            (tr("SASCM"), sascm_text, tr("纵向扩展硬件"), GREEN if sascm_ok else RED),
            (tr("毫米波雷达"), radar_text, tr("原车雷达目标检测"), GREEN if radar_ok else RED),
        )
        for i, (title, value, sub, dot) in enumerate(mid_cards):
            r = rl.Rectangle(rect.x + i * (mid_w + gap), y2, mid_w, mid_h)
            self._status_card(r, title, str(value), str(sub), dot)
