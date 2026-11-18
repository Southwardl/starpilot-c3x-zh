"""实测 EPS 拒绝转向扭矩的速度阈值。

原理：GM 的 steerFaultTemporary 直接来自 PSCMStatus.LKATorqueDeliveredStatus == 2
（PSCM 报告「扭矩限制」）。按速度分档统计它出现的比例，即可定位 EPS 拒绝执行
转向扭矩的速度区间。

用法：
  /usr/local/venv/bin/python3 /tmp/eps_speed_test.py [秒数]

建议驾驶方式：
  从 0 缓慢加速到 80+ km/h，再缓慢减速回 0，重复 2-3 次，
  全程让 openpilot 处于接合状态（横向激活时数据最有意义）。

输出：
  /data/eps_speed_test.csv   逐帧原始数据
  屏幕/终端打印按 5 km/h 分档的统计表
"""
import csv
import sys
import time
from collections import defaultdict

sys.path.insert(0, "/data/openpilot")

import cereal.messaging as messaging  # noqa: E402

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 300.0
CSV_PATH = "/data/eps_speed_test.csv"
BIN = 5.0  # km/h 分档宽度


def main():
    sm = messaging.SubMaster(["carState", "carControl", "selfdriveState"])
    # bin -> [总帧数, 故障帧数, latActive帧数, latActive且故障帧数]
    stats = defaultdict(lambda: [0, 0, 0, 0])
    rows = []
    t0 = time.time()
    print(f"开始记录 {DURATION:.0f}s — 请 0→80 km/h 缓慢往复，保持接合")

    while time.time() - t0 < DURATION:
        sm.update(20)
        if not (sm.valid["carState"] and sm.updated["carState"]):
            continue
        cs = sm["carState"]
        lat = bool(sm["carControl"].latActive) if sm.valid["carControl"] else False
        ss = sm["selfdriveState"] if sm.valid["selfdriveState"] else None
        st = str(ss.state) if ss else "?"
        v = cs.vEgo * 3.6
        fault = bool(cs.steerFaultTemporary)
        perm = bool(cs.steerFaultPermanent)

        b = int(v // BIN) * BIN
        s = stats[b]
        s[0] += 1
        if fault:
            s[1] += 1
        if lat:
            s[2] += 1
            if fault:
                s[3] += 1

        rows.append((round(time.time() - t0, 2), round(v, 1), int(fault), int(perm),
                     int(lat), st, round(float(cs.steeringAngleDeg), 1)))

    with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_s", "v_kph", "steer_fault_tmp", "steer_fault_perm",
                    "lat_active", "sd_state", "steer_angle_deg"])
        w.writerows(rows)

    print(f"\n  样本 {len(rows)} 帧 → {CSV_PATH}")
    print(f"\n  {'速度档':>10}  {'帧数':>6}  {'故障%':>7}  {'latActive帧':>11}  {'latActive且故障%':>16}")
    print("  " + "-" * 60)
    for b in sorted(stats):
        total, fault, lat, lat_fault = stats[b]
        fp = 100.0 * fault / total if total else 0
        lap = 100.0 * lat_fault / lat if lat else 0
        flag = ""
        if fault == 0 and total > 5:
            flag = "  ← 全程无故障"
        elif fault == total and total > 5:
            flag = "  ← 全程故障"
        print(f"  {b:6.0f}-{b + BIN:<3.0f}  {total:6d}  {fp:6.1f}%  {lat:11d}  {lap:15.1f}%{flag}")

    # 找分界点
    bins = sorted(b for b in stats if stats[b][0] >= 5)
    ok = [b for b in bins if stats[b][1] == 0]
    bad = [b for b in bins if stats[b][1] == stats[b][0]]
    if ok and bad:
        print(f"\n  ★ 全程无故障的最低速度档: {min(ok):.0f}-{min(ok)+BIN:.0f} km/h")
        print(f"  ★ 全程故障的最高速度档: {max(bad):.0f}-{max(bad)+BIN:.0f} km/h")
        print(f"  → EPS 阈值大致在 {max(bad)+BIN:.0f} ~ {min(ok):.0f} km/h 之间")


if __name__ == "__main__":
    main()
