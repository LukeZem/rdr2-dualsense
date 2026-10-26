"""Glue between the controller I/O thread, the active driver and the haptics backend."""
from __future__ import annotations

import csv
import queue
import threading
import time
from collections import deque
from pathlib import Path
from typing import Optional

from ds5.device import DualSense, InputState
from ds5.haptics import AudioHaptics, Cue, HapticLibrary, RumbleHaptics, SpeakerOut
from gameaudio.library import GameAudio, find_game_dir
from sim.engine import Frame, StaticDriver

MAX_KICK_DELAY_MS = 25.0


class Runtime:
    def __init__(self, base: Path) -> None:
        self.base = base
        self.game_dir = find_game_dir()
        self.game = GameAudio(self.game_dir, base / "data" / "sound_labels.json")
        self.library = HapticLibrary(base / "data" / "haptics.json", self.game)
        self.ds = DualSense()
        self.connected = False
        self.haptics = None
        self.haptics_mode = "off"
        self.haptics_error = ""
        self.sound_mode = "off"              # pc | controller | off
        self.sound_gain = 0.5
        self.sound_error = ""
        self.speaker: Optional[SpeakerOut] = None
        self.driver = StaticDriver()
        self.history: deque = deque(maxlen=1000)       # (t, r2, l2, game_rt) ~4 s at 250 Hz
        self.shot_marks: deque = deque(maxlen=64)
        self.events: queue.Queue = queue.Queue()
        self.frame: Optional[Frame] = None
        self.state = InputState()
        self._csv_file = None
        self._csv = None
        self._csv_lock = threading.Lock()
        self.recording_path: Optional[Path] = None

    # ---------- lifecycle ----------
    def connect(self) -> None:
        self.ds.open()
        self.ds.start(self._on_input)
        self.connected = True

    def close(self) -> None:
        self.stop_recording()
        if self.connected:
            self.ds.close()
            self.connected = False
        if self.haptics:
            self.haptics.close()
            self.haptics = None
        if self.speaker:
            self.speaker.close()
            self.speaker = None

    # ---------- haptics ----------
    def set_haptics(self, mode: str, exclusive: bool = False) -> None:
        old, self.haptics = self.haptics, None
        if old:
            old.close()
        self.haptics_error = ""
        try:
            if mode == "audio":
                self.haptics = AudioHaptics(self.library, exclusive=exclusive)
            elif mode == "rumble":
                self.haptics = RumbleHaptics(self.library)
        except Exception as e:
            self.haptics_error = str(e)
            mode = "off"
        self.haptics_mode = mode

    def set_sound(self, mode: str, gain: Optional[float] = None) -> None:
        """Where the game's own recordings play while you shoot: PC speakers, controller speaker or off."""
        if gain is not None:
            self.sound_gain = gain
        self.sound_error = ""
        if mode == "pc" and self.speaker is None:
            try:
                self.speaker = SpeakerOut()
            except Exception as e:
                self.sound_error, mode = str(e), "off"
        elif mode != "pc" and self.speaker is not None:
            self.speaker.close()
            self.speaker = None
        if mode == "controller" and not isinstance(self.haptics, AudioHaptics):
            self.sound_error, mode = "controller speaker needs USB audio haptics", "off"
        self.sound_mode = mode
        if self.speaker:
            self.speaker.gain = self.sound_gain
        if isinstance(self.haptics, AudioHaptics):
            self.haptics.sound_gain = self.sound_gain

    @property
    def kick_delay_ms(self) -> float:
        """How long the trigger recoil waits so it lands together with the audio haptics."""
        if isinstance(self.haptics, AudioHaptics):
            return min(MAX_KICK_DELAY_MS, self.haptics.latency_ms)
        return 0.0

    def play(self, cue: Cue | str | None) -> None:
        if not cue:
            return
        cue = self.library.pick(Cue(cue) if isinstance(cue, str) else cue)
        h = self.haptics
        if h:
            h.play(cue)
        if self.sound_mode != "off":
            buf = self.library.get_audio(cue)
            if buf is not None:
                if self.sound_mode == "pc" and self.speaker:
                    self.speaker.play(buf)
                elif self.sound_mode == "controller" and isinstance(h, AudioHaptics):
                    h.play_sound(buf)

    # ---------- recording ----------
    def start_recording(self) -> Path:
        logs = self.base / "logs"
        logs.mkdir(exist_ok=True)
        self.recording_path = logs / time.strftime("trace-%Y%m%d-%H%M%S.csv")
        self._csv_file = open(self.recording_path, "w", newline="", encoding="utf-8")
        w = csv.writer(self._csv_file)
        w.writerow(["t", "r2", "l2", "r2_feedback", "l2_feedback", "effect_state", "game_rt", "state",
                    "r2_block", "l2_block", "events"])
        self._csv = w
        return self.recording_path

    def stop_recording(self) -> None:
        with self._csv_lock:
            f, self._csv, self._csv_file = self._csv_file, None, None
            if f:
                f.close()

    # ---------- I/O thread ----------
    def _on_input(self, s: InputState):
        frame = self.driver.update(s)
        for cue in frame.haptics:
            self.play(cue)
        for e in frame.events:
            if e["type"] in ("shot", "dry"):
                self.shot_marks.append(e["t"])
            self.events.put(e)
        h = self.haptics
        frame.out.rumble = h.tick(s.t) if isinstance(h, RumbleHaptics) else None
        self.history.append((s.t, s.r2, s.l2, frame.game_rt))
        self.frame, self.state = frame, s
        with self._csv_lock:
            if self._csv:
                self._csv.writerow([f"{s.t:.4f}", s.r2, s.l2, f"0x{s.r2_feedback:02X}",
                                    f"0x{s.l2_feedback:02X}", f"0x{s.effect_state:02X}", frame.game_rt,
                                    frame.state, frame.out.r2.hex(), frame.out.l2.hex(),
                                    ";".join(e["type"] for e in frame.events)])
        return frame.out
