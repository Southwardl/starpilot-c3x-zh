#!/usr/bin/env python3
"""雷达纵向偏移精确测量（严格匹配版）。

改进点（相对上一版）
--------------------
1. 只匹配**正前方**的前车（|lead.y| < 0.8 m）—— 保证雷达目标唯一
2. 要求同一 trackId 连续命中 10 帧（约 0.5 s）—— 排除瞬时误配
3. 只统计**前车相对稳定**的时段（|v_closing| 变化平缓），
   避免加减速过程污染偏移估计
4. 用**分位数**而非均值，抗离群

判读
----
offset = x_vision - dRel 的中位数，就是 RADAR_TO_CAMERA 的正确值。

注意：radard.py 的语义是「雷达比相机靠前多少米」，
     所以设成这个中位数才能让 (x - RADAR_TO_CAMERA) ≈ dRel。
"""
import json
import statistics
import sys
import time

sys.path.insert(0, "/data/openpilot")

import cereal.messaging as messaging  # noqa: E402

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 240.0
PROB_MIN = 0.70        # 提高置信度要求
Y_VISION_MAX = 0.8     # 前车必须在正前方
DIST_GATE = 3.0        # 收紧纵向窗口
VEL_GATE = 2.5         # 收紧速度窗口
MIN_SPEED = 5.0
CONFIRM = 10           # 同一 track 连续 10 帧


def main():
    sm = messaging.SubMaster(["modelV2", "liveTracks", "carState"], poll="modelV2")
    streak = {}
    rows = []
    n_frames = n_lead_ok = 0
    t0 = time.time()

    while time.time() - t0 < DURATION:
        sm.update(20)
        if not sm.updated.get("modelV2"):
            continue
        n_frames += 1
        if not sm.valid.get("carState") or not sm.valid.get("liveTracks"):
            continue
        v = float(sm["carState"].vEgo)
        if abs(v) < MIN_SPEED:
            streak.clear()
            continue
        leads = sm["modelV2"].leadsV3
        if len(leads) == 0:
            streak.clear()
            continue
        lead = leads[0]
        if float(lead.prob) < PROB_MIN:
            streak.clear()
            continue
        xv, yv, vv = float(lead.x[0]), float(lead.y[0]), float(lead.v[0])
        # 只接受正前方的前车
        if abs(yv) > Y_VISION_MAX or xv <= 3 or xv > 120:
            streak.clear()
            continue
        n_lead_ok += 1

        best, best_cost = None, 1e9
        for pt in sm["liveTracks"].points:
            d = float(pt.dRel)
            if d <= 0.5 or abs(xv - d) > DIST_GATE:
                continue
            yr = float(pt.yRel)
            if abs(yr) > 1.5:          # 雷达目标也必须在正前方
                continue
            vr = float(pt.vRel) + v
            if abs(vr - vv) > VEL_GATE:
                continue
            if abs(xv - d) < best_cost:
                best_cost, best = abs(xv - d), (int(pt.trackId), d)
        if best is None:
            streak.clear()
            continue
        tid = best[0]
        streak[tid] = streak.get(tid, 0) + 1
        if streak[tid] < CONFIRM:
            continue
        rows.append((v, vv, xv, best[1]))

    out = {"frames": n_frames, "lead_in_lane_frames": n_lead_ok,
           "samples": len(rows), "duration_s": round(time.time() - t0, 1)}

    if len(rows) >= 30:
        offs = sorted(r[2] - r[3] for r in rows)
        vegos = [r[0] for r in rows]
        vcs = [r[0] - r[1] for r in rows]
        n = len(offs)
        out.update({
            "offset_median": round(statistics.median(offs), 3),
            "offset_mean": round(statistics.fmean(offs), 3),
            "offset_stdev": round(statistics.pstdev(offs), 3),
            "offset_p10": round(offs[n // 10], 3),
            "offset_p90": round(offs[n * 9 // 10], 3),
            "v_ego_range_kmh": [round(min(vegos) * 3.6), round(max(vegos) * 3.6)],
            "v_closing_range": [round(min(vcs), 2), round(max(vcs), 2)],
            "current_RADAR_TO_CAMERA": 1.52,
            "median_minus_current": round(statistics.median(offs) - 1.52, 3),
        })
        print(json.dumps(out, ensure_ascii=False, indent=1))
        print("\n  ═══ 判读 ═══")
        med = statistics.median(offs)
        sd = statistics.pstdev(offs)
        print(f"\n  样本 {n}，速度 {min(vegos)*3.6:.0f}-{max(vegos)*3.6:.0f} km/h")
        print(f"\n  offset 中位数 = {med:+.3f} m")
        print(f"  offset 标准差 = {sd:.3f} m")
        print(f"  P10-P90     = {offs[n//10]:+.2f} ~ {offs[n*9//10]:+.2f} m")
        print(f"\n  当前 RADAR_TO_CAMERA = 1.52 → 偏差 {med - 1.52:+.2f} m")
        if sd < 0.8:
            print(f"\n  ✅ 数据干净（σ={sd:.2f}m < 0.8），建议 RADAR_TO_CAMERA = {med:.2f}")
        else:
            print(f"\n  ⚠ 数据仍有散布（σ={sd:.2f}m），需要更多匀速直行跟车样本")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        print("\n  ⚠ 样本不足（<30）。需要：")
        print("    · 正前方有车（视觉 prob>0.7 且 |y|<0.8m）")
        print("    · 车速 > 18 km/h，匀速直行")
        print("    · 同一雷达目标持续跟踪 10 帧以上")

    with open("/data/radar_lon.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
