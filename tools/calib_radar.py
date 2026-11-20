#!/usr/bin/env python3
"""雷达-视觉融合完整校准：同时测纵向偏移、横向比例、横向偏移。

背景
----
radard.py 的融合判据：
    offset_vision_dist = lead.x[0] - RADAR_TO_CAMERA      # 纵向对齐
    lat_sane = abs(track.yRel + lead.y[0]) < ...          # 横向对齐

  · RADAR_TO_CAMERA 是全局常量（默认 1.52），把相机测的 x 搬到雷达原点
  · track.yRel 由 radar_interface.py 算：sin(azimuth) * distance * sign
  · 视觉 y 是「右正」，雷达 yRel 是「左正」，所以理想情况 yRel ≈ -lead.y

输出三项诊断
------------
1. 纵向偏移 OFF_LON = median(lead.x - track.dRel)
   → RADAR_TO_CAMERA 应设为此值

2. 横向比例 RATIO = median(track.yRel / -lead.y)
   → 应为 1.0；明显偏离说明方位角换算或安装角度有缩放误差

3. 横向残差 RESID = median(track.yRel + lead.y)
   → 应为 0；恒定非零说明有固定横向安装偏移

用法：
  /usr/local/venv/bin/python3 /tmp/calib_radar.py [秒数]
建议驾驶：20-80 km/h 跟车，走有弯道的路段，让前车横向有变化（变道/弯道）。
结果：/data/radar_calib.json
"""
import json
import statistics
import sys
import time
from collections import defaultdict

sys.path.insert(0, "/data/openpilot")

import cereal.messaging as messaging  # noqa: E402

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 240.0
PROB_MIN = 0.55
DIST_GATE = 6.0      # 纵向匹配窗口 (m)
VEL_GATE = 4.0       # 速度差上限 (m/s)
MIN_SPEED = 5.0      # 自车速度下限 (m/s)
CONFIRM = 3          # 同一 trackId 连续命中
# 横向窗口：不能用「接近 0」，否则只能采到正前方的目标，测不出比例。
# 允许较大的横向差，靠速度和纵向距离匹配。
Y_GATE = 4.0
Y_VISION_MIN = 0.15  # 视觉横向至少偏这么多才用于比例估计


def main():
    sm = messaging.SubMaster(["modelV2", "liveTracks", "carState"], poll="modelV2")
    streak = defaultdict(int)
    samples = []          # (trackId, x_v, y_v, v_v, dRel, yRel, vRel, vEgo, prob)
    n_lead = 0
    n_frames = 0
    t0 = time.time()

    while time.time() - t0 < DURATION:
        sm.update(20)
        if not sm.updated.get("modelV2"):
            continue
        n_frames += 1
        if not sm.valid.get("carState") or not sm.valid.get("liveTracks"):
            continue
        cs = sm["carState"]
        v_ego = float(cs.vEgo)
        if abs(v_ego) < MIN_SPEED:
            streak.clear()
            continue

        pts = sm["liveTracks"].points
        leads = sm["modelV2"].leadsV3
        if len(leads) == 0:
            streak.clear()
            continue
        lead = leads[0]
        prob = float(lead.prob)
        if prob < PROB_MIN:
            streak.clear()
            continue
        x_v, y_v, v_v = float(lead.x[0]), float(lead.y[0]), float(lead.v[0])
        if x_v <= 3 or x_v > 120:
            continue
        n_lead += 1

        best = None
        best_cost = 1e9
        for pt in pts:
            d = float(pt.dRel)
            if d <= 1:
                continue
            if abs(x_v - d) > DIST_GATE:
                continue
            yr = float(pt.yRel)
            if abs(yr + y_v) > Y_GATE:
                continue
            v_radar = float(pt.vRel) + v_ego
            if abs(v_radar - v_v) > VEL_GATE:
                continue
            cost = abs(x_v - d) + 0.5 * abs(yr + y_v)
            if cost < best_cost:
                best_cost = cost
                best = (int(pt.trackId), d, yr, v_radar)

        if best is None:
            streak.clear()
            continue
        tid = best[0]
        streak[tid] += 1
        if streak[tid] < CONFIRM:
            continue

        samples.append((tid, x_v, y_v, v_v, best[1], best[2], v_radar, v_ego, prob))

    out = {"frames": n_frames, "duration_s": round(time.time() - t0, 1),
           "frames_with_lead": n_lead, "samples": len(samples)}

    if samples:
        lon = [s[1] - s[4] for s in samples]
        resid = [s[5] + s[2] for s in samples]
        # 比例只用横向足够大的样本，避免除零噪声
        ratio = [s[5] / (-s[2]) for s in samples if abs(s[2]) >= Y_VISION_MIN]
        dists = [s[1] for s in samples]

        def stats(v, name):
            if not v:
                return None
            v = sorted(v)
            return {f"{name}_median": round(statistics.median(v), 3),
                    f"{name}_p25": round(v[len(v) // 4], 3),
                    f"{name}_p75": round(v[len(v) * 3 // 4], 3),
                    f"{name}_mean": round(statistics.fmean(v), 3),
                    f"{name}_stdev": round(statistics.pstdev(v), 3),
                    f"{name}_n": len(v)}

        out.update(stats(lon, "lon_offset"))
        out.update(stats(resid, "lat_resid"))
        out.update(stats(ratio, "lat_ratio"))
        out["distance_range_m"] = [round(min(dists), 1), round(max(dists), 1)]
        out["unique_tracks"] = len({s[0] for s in samples})

        print(json.dumps(out, ensure_ascii=False, indent=1))
        print("\n  === 判读 ===")
        lon_m = statistics.median(lon)
        print(f"  ① 纵向: RADAR_TO_CAMERA 建议设为 {lon_m:.2f} m"
              f"（当前 1.52，差 {lon_m - 1.52:+.2f} m）")
        if ratio:
            r = statistics.median(ratio)
            print(f"  ② 横向比例: {r:.3f}（理想 1.0）"
                  f"{'  ⚠ 需要缩放方位角' if abs(r - 1.0) > 0.08 else '  ✅ 正常'}")
        r_med = statistics.median(resid)
        print(f"  ③ 横向残差: {r_med:+.3f} m（理想 0）"
              f"{'  ⚠ 有固定横向偏移' if abs(r_med) > 0.25 else '  ✅ 正常'}")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        print("\n  ⚠ 无有效样本。要求：")
        print("    · 车速 > 18 km/h")
        print("    · 前方有车，视觉 prob > 0.55")
        print("    · 雷达目标速度与视觉前车速度一致")

    with open("/data/radar_calib.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
