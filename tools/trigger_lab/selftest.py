"""Headless check that the controller accepts our output reports.

Applies every trigger effect mode to R2 (gently) and reads back the active
effect nibble the controller reports in its input report. Restores Off at the end.
Usage: python selftest.py
"""
import time

from ds5 import effects
from ds5.device import DualSense, find_conflicting_processes, OutputState

TESTS = [
    ("Off", effects.off()),
    ("Feedback", effects.feedback(3, 2)),
    ("Zone curve", effects.multi_feedback([0, 1, 1, 2, 3, 0, 0, 0, 0, 0])),
    ("Weapon", effects.weapon(4, 6, 2)),
    ("Bow", effects.bow(1, 6, 2, 2)),
    ("Galloping", effects.galloping(0, 9, 4, 7, 2)),
    ("Vibration", effects.vibration(9, 1, 20)),
    ("Machine", effects.machine(8, 9, 1, 1, 5, 2)),
    ("Simple Feedback", effects.simple_feedback(200, 40)),
    ("Simple Weapon", effects.simple_weapon(150, 200, 40)),
    ("Simple Vibration", effects.simple_vibration(20, 30, 250)),
    ("Limited Feedback", effects.limited_feedback(200, 2)),
    ("Limited Weapon", effects.limited_weapon(150, 200, 2)),
    ("Off", effects.off()),
]


def main() -> None:
    conflicts = find_conflicting_processes()
    if conflicts:
        print("WARNING: running programs that also drive the controller:", ", ".join(conflicts))
    ds = DualSense()
    ds.open()
    print(f"{ds.name} via {ds.transport}")
    ds.start(lambda s: None)
    time.sleep(1.2)
    print(f"input report rate: {ds.report_rate:.0f} Hz, battery {ds.last_input.battery * 10}%")
    for name, block in TESTS:
        ds.write(OutputState(r2=block), force=True)
        time.sleep(0.25)
        s = ds.last_input
        print(f"{name:<17} sent {effects.describe(block)} | effect-state 0x{s.effect_state:02X}"
              f" r2-fb 0x{s.r2_feedback:02X} l2-fb 0x{s.l2_feedback:02X}")
    # Does someone else overwrite our effect? Hold one and watch.
    ds.write(OutputState(r2=effects.feedback(3, 2)), force=True)
    seen = set()
    for _ in range(20):
        time.sleep(0.1)
        seen.add(ds.last_input.effect_state)
    print("effect-state while holding Feedback for 2 s:", sorted(hex(x) for x in seen))
    ds.close()


if __name__ == "__main__":
    main()
