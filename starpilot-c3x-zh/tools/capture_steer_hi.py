"""聚焦「43 km/h 以上转向仍不可用」的现场采集。

只在车速 > 5 km/h 时记录，避免停车噪声刷屏。
每次关键状态变化（steerFault / state / alert / latActive）写一行。

用法：/usr/local/venv/bin/python3 /tmp/capture_steer_hi.py [秒数]
输出：/data/steer_hi.log
"""
import sys
import time

sys.path.insert(0, "/data/openpilot")

import cereal.messaging as messaging  # noqa: E402

DURATION = float(sys.argv[1]) if len(sys.argv) > 1 else 240.0
LOG = "/data/steer_hi.log"
_fh = open(LOG, "w", buffering=1)

stats = {"frames_speed": 0, "frames_above43": 0, "fault_above43": 0,
         "latactive_above43": 0, "max_speed": 0.0, "max_speed_fault": None}


def emit(t, text):
    line = f"[{t:7.1f}s] {text}"
    print(line)
    _fh.write(line + "\n")


def main():
    sm = messaging.SubMaster(["carState", "selfdriveState", "carControl"])
    t0 = time.time()
    last = None
    emit(0.0, f"START {DURATION:.0f}s — 请开到 50-70 km/h 并尝试接合")

    while time.time() - t0 < DURATION:
        sm.update(20)
        t = time.time() - t0
        if not (sm.valid["carState"] and sm.valid["selfdriveState"]):
            continue

        cs = sm["carState"]
        ss = sm["selfdriveState"]
        cc = sm["carControl"] if sm.valid["carControl"] else None
        v_kph = cs.vEgo * 3.6
        if v_kph < 5:
            continue

        stats["frames_speed"] += 1
        stats["max_speed"] = max(stats["max_speed"], v_kph)
        above43 = v_kph >= 43.0
        if above43:
            stats["frames_above43"] += 1
            if cs.steerFaultTemporary:
                stats["fault_above43"] += 1
                stats["max_speed_fault"] = v_kph
            if cc is not None and cc.latActive:
                stats["latactive_above43"] += 1

        key = (bool(cs.steerFaultTemporary), str(ss.state), str(ss.alertText1),
               bool(cc.latActive) if cc else None, bool(ss.enabled))
        if key != last:
            last = key
            lat = bool(cc.latActive) if cc else None
            tq = f"{cc.actuators.torque:+.3f}" if cc else "?"
            emit(t, (f"v={v_kph:5.1f} {'≥43' if above43 else '<43'} "
                     f"steerFault={cs.steerFaultTemporary!s:<5} "
                     f"state={str(ss.state):<13} enabled={ss.enabled!s:<5} "
                     f"latActive={lat!s:<5} torque={tq:<7} alert1={ss.alertText1!r}"))

    emit(DURATION, (
        f"END 行车帧={stats['frames_speed']} ≥43帧={stats['frames_above43']} "
        f"≥43时故障帧={stats['fault_above43']} ≥43时latActive帧={stats['latactive_above43']} "
        f"最高速={stats['max_speed']:.1f} 故障时最高速={stats['max_speed_fault']}"))
    _fh.close()


if __name__ == "__main__":
    main()
