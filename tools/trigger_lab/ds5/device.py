"""DualSense HID transport: input parsing and output report building (USB + Bluetooth).

Report layouts (offsets are into the report *payload*, i.e. after the report
id on USB and after id + 1 tag byte on Bluetooth):

Input (USB id 0x01 / 64 bytes, BT id 0x31 / 78 bytes):
    0..5   LX LY RX RY L2 R2
    6      sequence counter
    7      d-pad (low nibble hat) + square/cross/circle/triangle
    8      L1 R1 L2 R2 Create Options L3 R3
    9      PS Touchpad Mute
    41     R2 trigger feedback state  (low nibble: stop location, high: status)
    42     L2 trigger feedback state
    47     active trigger effects    (low nibble: R2, high nibble: L2)
    52     battery (low nibble 0-10) / charging state (high nibble)

Output payload (USB id 0x02 / 48 bytes, BT id 0x31 / 78 bytes + CRC32):
    0      valid_flag0  (0x01 rumble, 0x02 rumble-not-haptics, 0x04 R2 effect, 0x08 L2 effect)
    1      valid_flag1  (0x04 lightbar, 0x40 motor power level)
    2, 3   rumble emulation right (high freq) / left (low freq)
    10     R2 effect block (11 bytes)
    21     L2 effect block (11 bytes)
    36     motor power reduction (low nibble triggers, high nibble rumble; 0 = full)
    38     valid_flag2  (0x02 lightbar setup, 0x04 improved rumble emulation)
    41     lightbar setup (0x02 = release lightbar from the boot animation)
    44..46 lightbar R G B
"""
from __future__ import annotations

import subprocess
import threading
import time
import zlib
from dataclasses import dataclass, field
from typing import Callable, Optional

import hid

from . import effects

SONY_VID = 0x054C
PIDS = {0x0CE6: "DualSense", 0x0DF2: "DualSense Edge"}

USB_INPUT_ID, USB_OUTPUT_ID, USB_OUTPUT_LEN = 0x01, 0x02, 48
BT_INPUT_ID, BT_OUTPUT_ID, BT_OUTPUT_LEN = 0x31, 0x31, 78

# Buttons (our own flat bitmask)
SQUARE, CROSS, CIRCLE, TRIANGLE = 1 << 0, 1 << 1, 1 << 2, 1 << 3
L1, R1, L2_BTN, R2_BTN = 1 << 4, 1 << 5, 1 << 6, 1 << 7
CREATE, OPTIONS, L3, R3 = 1 << 8, 1 << 9, 1 << 10, 1 << 11
PS, TOUCHPAD, MUTE = 1 << 12, 1 << 13, 1 << 14
DPAD_UP, DPAD_RIGHT, DPAD_DOWN, DPAD_LEFT = 1 << 15, 1 << 16, 1 << 17, 1 << 18

_HAT = {0: DPAD_UP, 1: DPAD_UP | DPAD_RIGHT, 2: DPAD_RIGHT, 3: DPAD_RIGHT | DPAD_DOWN,
        4: DPAD_DOWN, 5: DPAD_DOWN | DPAD_LEFT, 6: DPAD_LEFT, 7: DPAD_LEFT | DPAD_UP}


@dataclass
class InputState:
    t: float = 0.0              # perf_counter() when the report arrived
    lx: int = 128
    ly: int = 128
    rx: int = 128
    ry: int = 128
    l2: int = 0
    r2: int = 0
    buttons: int = 0
    r2_feedback: int = 0        # raw byte 41
    l2_feedback: int = 0        # raw byte 42
    effect_state: int = 0       # raw byte 47
    battery: int = 0
    seq: int = 0

    def pressed(self, mask: int) -> bool:
        return bool(self.buttons & mask)


@dataclass
class OutputState:
    r2: bytes = field(default_factory=effects.off)
    l2: bytes = field(default_factory=effects.off)
    rumble: Optional[tuple[int, int]] = None      # (left/low, right/high) 0-255, None = leave haptics alone
    lightbar: Optional[tuple[int, int, int]] = None
    trigger_power_reduction: int = 0              # 0 (full) .. 7


def _parse(report: list[int], offset: int, now: float) -> InputState:
    d = report[offset:]
    b0, b1, b2 = d[7], d[8], d[9]
    buttons = _HAT.get(b0 & 0x0F, 0)
    buttons |= (SQUARE if b0 & 0x10 else 0) | (CROSS if b0 & 0x20 else 0)
    buttons |= (CIRCLE if b0 & 0x40 else 0) | (TRIANGLE if b0 & 0x80 else 0)
    for bit, mask in enumerate((L1, R1, L2_BTN, R2_BTN, CREATE, OPTIONS, L3, R3)):
        if b1 & (1 << bit):
            buttons |= mask
    for bit, mask in enumerate((PS, TOUCHPAD, MUTE)):
        if b2 & (1 << bit):
            buttons |= mask
    return InputState(t=now, lx=d[0], ly=d[1], rx=d[2], ry=d[3], l2=d[4], r2=d[5],
                      buttons=buttons, r2_feedback=d[41], l2_feedback=d[42],
                      effect_state=d[47], battery=d[52] & 0x0F, seq=d[6])


def find_conflicting_processes() -> list[str]:
    """Other programs that write to the DualSense and would fight with us."""
    try:
        out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout.lower()
    except OSError:
        return []
    known = ["dsx.exe", "ds4windows.exe", "dualsensex.exe", "rdr2.exe"]
    return [k for k in known if f'"{k}"' in out]


class DualSense:
    """Owns the controller. Call start(on_input) - on_input runs on the I/O thread
    for every input report (or every ~10 ms if none arrive) and may return an
    OutputState to send."""

    def __init__(self) -> None:
        self._dev: Optional[hid.device] = None
        self.transport = ""
        self.name = ""
        self._thread: Optional[threading.Thread] = None
        self._running = False
        self._bt_seq = 0
        self._last_sent: Optional[bytes] = None
        self._lightbar_released = False
        self.report_rate = 0.0
        self.last_input = InputState()
        self.error: Optional[str] = None

    # ---------- connection ----------
    def open(self) -> None:
        candidates = [d for d in hid.enumerate(SONY_VID)
                      if d["product_id"] in PIDS and d.get("usage_page") == 1 and d.get("usage") == 5]
        if not candidates:
            raise RuntimeError("No DualSense found. Connect it via USB (recommended) or Bluetooth.")
        # bus_type: 1 = USB, 2 = Bluetooth. Prefer USB: lower latency and audio haptics.
        candidates.sort(key=lambda d: 0 if d.get("bus_type") == 1 else 1)
        last_err = None
        for info in candidates:
            dev = hid.device()
            try:
                dev.open_path(info["path"])
            except OSError as e:
                last_err = e
                continue
            self._dev = dev
            self.name = PIDS[info["product_id"]]
            self.transport = "USB" if info.get("bus_type") == 1 else "Bluetooth"
            if self.transport == "Bluetooth":
                # Reading the calibration feature report switches BT from the
                # reduced 0x01 report to the full 0x31 report.
                try:
                    dev.get_feature_report(0x05, 41)
                except OSError:
                    pass
            return
        raise RuntimeError(f"DualSense found but could not be opened: {last_err}")

    def close(self) -> None:
        self.stop()
        if self._dev:
            try:
                self.write(OutputState(), force=True)   # never leave a stiff trigger behind
            except OSError:
                pass
            self._dev.close()
            self._dev = None

    # ---------- output ----------
    def build_payload(self, out: OutputState) -> bytearray:
        p = bytearray(47)
        p[0] = 0x04 | 0x08                               # both trigger effects valid
        p[1] = 0x40                                      # motor power level valid
        if out.rumble is not None:
            p[0] |= 0x01 | 0x02                          # rumble emulation, use rumble not audio haptics
            p[38] |= 0x04                                # improved rumble emulation (fw >= 2.24)
            p[3], p[2] = out.rumble[0] & 0xFF, out.rumble[1] & 0xFF
        p[10:21] = out.r2
        p[21:32] = out.l2
        p[36] = out.trigger_power_reduction & 0x07
        if out.lightbar is not None:
            p[1] |= 0x04
            if not self._lightbar_released:
                p[38] |= 0x02
                p[41] = 0x02
            p[44], p[45], p[46] = (c & 0xFF for c in out.lightbar)
        return p

    def write(self, out: OutputState, force: bool = False) -> bool:
        payload = bytes(self.build_payload(out))
        if not force and payload == self._last_sent:
            return False
        if self.transport == "USB":
            report = bytes([USB_OUTPUT_ID]) + payload
        else:
            buf = bytearray(BT_OUTPUT_LEN)
            buf[0] = BT_OUTPUT_ID
            buf[1] = (self._bt_seq & 0x0F) << 4
            buf[2] = 0x10
            buf[3:3 + len(payload)] = payload
            self._bt_seq = (self._bt_seq + 1) & 0x0F
            crc = zlib.crc32(bytes([0xA2]) + bytes(buf[:74])) & 0xFFFFFFFF
            buf[74:78] = crc.to_bytes(4, "little")
            report = bytes(buf)
        self._dev.write(report)
        if out.lightbar is not None:
            self._lightbar_released = True
        self._last_sent = payload
        return True

    # ---------- input loop ----------
    def start(self, on_input: Callable[[InputState], Optional[OutputState]]) -> None:
        self._running = True
        self._thread = threading.Thread(target=self._loop, args=(on_input,), name="ds5-io", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._running = False
        if self._thread and self._thread is not threading.current_thread():
            self._thread.join(timeout=1.0)
        self._thread = None

    def _loop(self, on_input) -> None:
        dev = self._dev
        n, t_rate = 0, time.perf_counter()
        state = self.last_input
        while self._running:
            try:
                report = dev.read(BT_OUTPUT_LEN, 10)
            except OSError as e:
                self.error = f"read failed: {e}"
                self._running = False
                break
            now = time.perf_counter()
            if report:
                if report[0] == USB_INPUT_ID and len(report) >= 64:
                    state = _parse(report, 1, now)
                elif report[0] == BT_INPUT_ID and len(report) >= 64:
                    state = _parse(report, 2, now)
                else:
                    continue                             # reduced BT report, ignore
                n += 1
                self.last_input = state
            else:
                state = InputState(**{**state.__dict__, "t": now})
            if now - t_rate >= 1.0:
                self.report_rate = n / (now - t_rate)
                n, t_rate = 0, now
            try:
                out = on_input(state)
                if out is not None:
                    self.write(out)
            except Exception as e:                       # keep the controller loop alive
                self.error = f"driver error: {e!r}"
