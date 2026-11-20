#!/usr/bin/env python3
"""诊断「前方静止车辆不刹车」—— 不依赖雷达必须看到目标。

上一版要求「雷达 60 米内有目标」才记录，结果 0 帧 ——
因为问题恰恰是雷达/视觉在远处看不到停着的车。

本版改为：只要车速 > 25 km/h 且正前方 80 米内出现**任一**证据
（雷达目标 或 视觉前车）就开始记录，从而能完整捕捉接近过程。

安全：只观测不控制，请随时准备人工刹车。
"""
import json
import sys
import time

sys.path.insert(0, "/data/openpilot")

import cereal.messaging as messaging  # noqa: E402

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 180.0
Y_GATE = 2.0
MIN_SPEED = 7.0     # >25 km/h
NEAR_DIST = 80.0


def main():
    sm = messaging.SubMaster(["modelV2", "radarState", "liveTracks", "carState",
                              "longitudinalPlan"], poll="modelV2")
    rows = []
    t0 = time.monotonic()

    while time.monotonic() - t0 < DURATION:
        sm.update(20)
        if not sm.updated.get("modelV2"):
            continue
        if not sm.valid.get("carState"):
            continue
        v = float(sm["carState"].vEgo)
        if v < MIN_SPEED:
            continue
        t = time.monotonic() - t0

        vis_prob, vis_x = 0.0, 999.0
        if len(sm["modelV2"].leadsV3) > 0:
            ld = sm["modelV2"].leadsV3[0]
            vis_prob, vis_x = float(ld.prob), float(ld.x[0])

        lead_on, lead_d = False, 999.0
        if sm.valid.get("radarState"):
            lo = sm["radarState"].leadOne
            lead_on = bool(lo.status)
            if lead_on:
                lead_d = float(lo.dRel)

        near_d = 999.0
        if sm.valid.get("liveTracks"):
            for pt in sm["liveTracks"].points:
                if abs(float(pt.yRel)) < Y_GATE:
                    d = float(pt.dRel)
                    if 0.5 < d < near_d:
                        near_d = d

        # 任一证据在范围内才记录
        if min(vis_x, near_d, lead_d) > NEAR_DIST:
            continue

        acc = 0.0
        if sm.valid.get("longitudinalPlan"):
            lp = sm["longitudinalPlan"]
            try:
                acc = float(lp.accels[0]) if len(lp.accels) > 0 else 0.0
            except Exception:
                acc = 0.0

        rows.append({"t": round(t, 1), "v": round(v, 2),
                     "vp": round(vis_prob, 2), "vx": round(vis_x, 1),
                     "lo": lead_on, "ld": round(lead_d, 1),
                     "nd": round(near_d, 1), "a": round(acc, 2)})

    out = {"recorded_frames": len(rows), "duration_s": round(time.monotonic() - t0, 1)}
    print(json.dumps(out, ensure_ascii=False, indent=1))

    if len(rows) < 15:
        print("\n  ⚠ 有效帧不足：需要 >25 km/h 且正前方 80 米内有目标/前车")
        return

    # 统计各环节首次可见距离（取每段的最大距离，代表最早检测到）
    def farthest(key, pred):
        vals = [r[key] for r in rows if pred(r) and r[key] < 900]
        return max(vals) if vals else None

    d_radar = farthest("nd", lambda r: r["nd"] < 900)
    d_vision = farthest("vx", lambda r: r["vp"] > 0.37)
    d_lead = farthest("ld", lambda r: r["lo"])
    d_brake = farthest("nd", lambda r: r["a"] < -0.5)

    out.update({"radar_farthest": d_radar, "vision_farthest": d_vision,
                "lead_farthest": d_lead, "brake_farthest": d_brake})
    print(f"\n  ═══ 各环节最远生效距离 ═══")
    print(f"    ① 雷达看到正前方目标   : {d_radar if d_radar else '—'} m")
    print(f"    ② 视觉 prob > 37%      : {d_vision if d_vision else '—'} m")
    print(f"    ③ 融合产生 leadOne     : {d_lead if d_lead else '—'} m")
    print(f"    ④ 发出减速指令         : {d_brake if d_brake else '—'} m")

    print(f"\n  采样分布（按距离分桶）:")
    bins = [(0, 15), (15, 25), (25, 40), (40, 60), (60, 80)]
    print(f"    {'距离段':>10} {'帧数':>6} {'有雷达':>7} {'视觉达标':>8} {'有lead':>7} {'在减速':>7}")
    for lo, hi in bins:
        seg = [r for r in rows if lo <= min(r["nd"], r["vx"]) < hi]
        if not seg:
            continue
        print(f"    {lo:4d}-{hi:3d}m {len(seg):6d} "
              f"{sum(1 for r in seg if r['nd']<900):7d} "
              f"{sum(1 for r in seg if r['vp']>0.37):8d} "
              f"{sum(1 for r in seg if r['lo']):7d} "
              f"{sum(1 for r in seg if r['a']<-0.5):7d}")

    print(f"\n  最近 25 帧明细:")
    print(f"    {'雷达':>7} {'视觉x':>7} {'vprob':>6} {'lead':>6} {'accel':>7} {'车速':>7}")
    for r in rows[-25:]:
        print(f"    {r['nd']:7.1f} {r['vx']:7.1f} {r['vp']:6.2f} "
              f"{(r['ld'] if r['lo'] else 0):6.1f} {r['a']:+7.2f} {r['v']*3.6:7.1f}")

    with open("/data/stopped_lead_diag2.json", "w") as f:
        json.dump({"out": out, "rows": rows}, f, ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
