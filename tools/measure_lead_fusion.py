#!/usr/bin/env python3
"""测量主界面「前车标记」与视觉原始值的偏差。

主界面画的是 radarState.leadOne（视觉+雷达融合结果）。
用户看到的「点位追着目标跑」= leadOne 与视觉真值之间有随速度变化的偏差。

本工具同时记录：
  · modelV2.leadsV3[0]   —— 纯视觉前车（真值参考）
  · radarState.leadOne   —— 融合后的前车（主界面画的）
  · radarState.leadsV3   —— 融合层自己的视觉前车
  · radarState.tracks    —— 雷达原始目标

分析
----
1. diff = leadOne.dRel - vision.x        （融合偏差）
2. 偏差是否随速度增长 -> 线性/时间滞后
3. leadOne 的 trackId 变化频率 -> 是否在目标间跳
4. 逐帧抖动幅度 -> 是否抖动

用法：/usr/local/venv/bin/python3 /tmp/measure_lead_fusion.py [秒数]
"""
import json
import statistics
import sys
import time

sys.path.insert(0, "/data/openpilot")

import cereal.messaging as messaging  # noqa: E402

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 240.0
MIN_SPEED = 4.0


def linfit(xs, ys):
    n = len(xs)
    if n < 5:
        return None, None, None
    mx, my = sum(xs) / n, sum(ys) / n
    sxx = sum((x - mx) ** 2 for x in xs)
    sxy = sum((x - mx) * (y - my) for x, y in zip(xs, ys))
    if sxx == 0:
        return my, 0.0, 0.0
    b = sxy / sxx
    a = my - b * mx
    ss_tot = sum((y - my) ** 2 for y in ys)
    ss_res = sum((y - (a + b * x)) ** 2 for x, y in zip(xs, ys))
    return a, b, (1 - ss_res / ss_tot if ss_tot > 0 else 0.0)


def main():
    sm = messaging.SubMaster(["modelV2", "radarState", "carState"], poll="modelV2")
    rows = []          # (v, x_vis, y_vis, d_lead, y_lead, status, trackId)
    track_ids = []
    prev_d = None
    jitter = []
    n_frames = 0
    t0 = time.time()

    while time.time() - t0 < DURATION:
        sm.update(20)
        if not sm.updated.get("modelV2"):
            continue
        n_frames += 1
        if not sm.valid.get("carState") or not sm.valid.get("modelV2"):
            continue
        v = float(sm["carState"].vEgo)
        if abs(v) < MIN_SPEED:
            continue
        leads = sm["modelV2"].leadsV3
        if len(leads) == 0 or float(leads[0].prob) < 0.5:
            continue
        xv, yv = float(leads[0].x[0]), float(leads[0].y[0])
        if xv <= 3 or xv > 120:
            continue

        d_lead = float("nan")
        y_lead = float("nan")
        status = "nodata"
        tid = -1
        if sm.valid.get("radarState"):
            rs = sm["radarState"]
            try:
                lo = rs.leadOne
                if lo.status:
                    d_lead = float(lo.dRel)
                    y_lead = float(lo.yRel)
                    status = str(lo.status)
                    tid = int(getattr(lo, "radarTrackId", -1))
            except Exception:
                pass

        rows.append((v, xv, yv, d_lead, y_lead, status, tid))
        if tid >= 0:
            track_ids.append(tid)
            if prev_d is not None and not (d_lead != d_lead):
                jitter.append(abs(d_lead - prev_d))
            prev_d = d_lead if not (d_lead != d_lead) else None

    out = {"frames": n_frames, "samples": len(rows),
           "duration_s": round(time.time() - t0, 1)}

    valid = [r for r in rows if r[5] != "nodata" and not (r[3] != r[3])]
    out["samples_with_lead"] = len(valid)

    if len(valid) >= 30:
        diffs = [r[3] - r[1] for r in valid]
        vegos = [r[0] for r in valid]
        diffs_y = [r[4] - r[2] for r in valid]

        a, b, r2 = linfit(vegos, diffs)

        out.update({
            "diff_d_median": round(statistics.median(diffs), 3),
            "diff_d_stdev": round(statistics.pstdev(diffs), 3),
            "diff_d_p10_p90": [round(sorted(diffs)[len(diffs)//10], 2),
                               round(sorted(diffs)[len(diffs)*9//10], 2)],
            "diff_y_median": round(statistics.median(diffs_y), 3),
            "diff_y_stdev": round(statistics.pstdev(diffs_y), 3),
            "v_ego_range_kmh": [round(min(vegos)*3.6), round(max(vegos)*3.6)],
            "fit_diff_vs_speed_slope": round(b, 4) if b is not None else None,
            "fit_diff_vs_speed_intercept": round(a, 3) if a is not None else None,
            "fit_diff_vs_speed_r2": round(r2, 3) if r2 is not None else None,
            "lead_status_counts": {s: sum(1 for r in valid if r[5] == s)
                                   for s in {r[5] for r in valid}},
            "track_switches": len({t for t in track_ids}),
            "jitter_median_m": round(statistics.median(jitter), 3) if jitter else None,
            "jitter_p90_m": round(sorted(jitter)[len(jitter)*9//10], 3) if jitter else None,
        })

        print(json.dumps(out, ensure_ascii=False, indent=1))
        print("\n  ═══ 判读 ═══")
        print(f"\n  样本 {len(valid)}，速度 {min(vegos)*3.6:.0f}-{max(vegos)*3.6:.0f} km/h")
        print(f"\n  ① 纵向偏差 (leadOne.dRel - 视觉x):")
        print(f"     中位数 {statistics.median(diffs):+.3f} m   标准差 {statistics.pstdev(diffs):.3f} m")
        print(f"     P10-P90 {out['diff_d_p10_p90'][0]:+.2f} ~ {out['diff_d_p10_p90'][1]:+.2f} m")
        print(f"\n  ② 偏差 vs 速度:  {a:+.2f} + ({b:+.4f}) × v   R²={r2:.3f}")
        if abs(b) > 0.02 and r2 > 0.3:
            print(f"     → ⚠ 偏差随速度变化！等效滞后 {b*1000:+.0f} ms")
            print(f"       这正是「速度越快偏得越多」的表现")
        else:
            print(f"     → 偏差与速度无显著相关（R²={r2:.2f}）")
        print(f"\n  ③ 横向偏差: 中位数 {statistics.median(diffs_y):+.3f} m  "
              f"标准差 {statistics.pstdev(diffs_y):.3f} m")
        print(f"\n  ④ 目标切换: 出现 {len({t for t in track_ids})} 个不同 trackId")
        if jitter:
            print(f"  ⑤ 逐帧抖动: 中位 {statistics.median(jitter):.3f} m，"
                  f"P90 {sorted(jitter)[len(jitter)*9//10]:.3f} m")
        print(f"\n  ⑥ leadOne 状态分布: {out['lead_status_counts']}")
    else:
        print(json.dumps(out, ensure_ascii=False, indent=1))
        print("\n  ⚠ 样本不足，需要有前车且车速>14km/h")

    with open("/data/lead_fusion.json", "w") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
