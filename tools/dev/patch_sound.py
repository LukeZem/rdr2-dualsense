"""One-off patch: play the game's recordings (same variant as the haptic) on PC or controller speaker."""
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "trigger_lab"


def edit(rel, pairs):
    p = ROOT / rel
    s = p.read_text(encoding="utf-8")
    for a, b in pairs:
        if a not in s:
            raise SystemExit(f"{rel}: not found: {a[:80]!r}")
        s = s.replace(a, b, 1)
    p.write_text(s, encoding="utf-8")


edit("ds5/haptics.py", [
    ('''@dataclass
class Cue:
    name: str
    gain: float = 1.0
    variant: Optional[int] = None
    speed: float = 1.0
''', '''@dataclass
class Cue:
    name: str
    gain: float = 1.0
    variant: Optional[int] = None
    speed: float = 1.0
    pan: Optional[float] = None       # re-pan at play time (e.g. which fist punched)
'''),
    ('''        self.buffers: dict[str, list[np.ndarray]] = {}
        self.kicks: dict[str, list[list[int]]] = {}''',
     '''        self.buffers: dict[str, list[np.ndarray]] = {}
        self.audio: dict[str, list[np.ndarray]] = {}      # the game recording behind each variant
        self.kicks: dict[str, list[list[int]]] = {}'''),
    ('''        self.buffers, self.kicks, self.source = {}, {}, {}''',
     '''        self.buffers, self.kicks, self.source, self.audio = {}, {}, {}, {}'''),
    ('''                if sounds:
                    src = f"game {layer['bank']} x{len(sounds)}"''',
     '''                if sounds:
                    src = f"game {layer['bank']} x{len(sounds)}"
                    self.audio.setdefault(name, [_speaker_audio(s) for s in sounds])'''),
    ('''        self.buffers[name], self.kicks[name] = bufs, kicks''',
     '''        self.buffers[name], self.kicks[name] = bufs, kicks
        self.audio[name] = [_speaker_audio(s) for s in sounds]'''),
    ('''    def get(self, cue: Cue) -> Optional[np.ndarray]:''',
     '''    def pick(self, cue: Cue) -> Cue:
        """Fix the variant up front so the haptic and the speaker sound use the same recording."""
        n = len(self.buffers.get(cue.name, []))
        if n and (cue.variant is None or not 0 <= cue.variant < n):
            cue = Cue(cue.name, cue.gain, random.randrange(n), cue.speed, cue.pan)
        return cue

    def get_audio(self, cue: Cue) -> Optional[np.ndarray]:
        """The game recording for this cue (None for synthesized-only recipes)."""
        recs = self.audio.get(cue.name)
        if not recs:
            return None
        buf = recs[(cue.variant or 0) % len(recs)]
        if abs(cue.speed - 1.0) > 1e-3:                    # Dead Eye: slower and deeper, like the game
            buf = _respeed(buf, cue.speed)
        return buf

    def get(self, cue: Cue) -> Optional[np.ndarray]:'''),
    ('''        buf = bufs[i]
        if abs(cue.speed - 1.0) > 1e-3:                    # slow motion: longer and deeper
            n = int(len(buf) / cue.speed)
            src = np.arange(n) * cue.speed
            buf = np.stack([np.interp(src, np.arange(len(buf)), buf[:, c]) for c in (0, 1)], axis=1)
        return buf.astype(np.float32) * cue.gain''',
     '''        buf = bufs[i]
        if abs(cue.speed - 1.0) > 1e-3:                    # slow motion: longer and deeper
            buf = _respeed(buf, cue.speed)
        if cue.pan is not None:                            # re-pan: strongest channel, placed at cue.pan
            mono = buf[:, int(np.argmax(np.abs(buf).sum(axis=0)))]
            gl, gr = _pan_gains(cue.pan)
            buf = np.stack([mono * gl, mono * gr], axis=1)
        return buf.astype(np.float32) * cue.gain'''),
    ('''class HapticLibrary:''',
     '''def _respeed(buf: np.ndarray, speed: float) -> np.ndarray:
    n = int(len(buf) / speed)
    src = np.arange(n) * speed
    return np.stack([np.interp(src, np.arange(len(buf)), buf[:, c]) for c in (0, 1)], axis=1).astype(np.float32)


def _speaker_audio(sound) -> np.ndarray:
    """A game sound as 48 kHz stereo float32 for the speakers."""
    d = sound.data()
    return np.stack([convert.resample(d[:, c], sound.rate) for c in (0, 1)], axis=1)


class HapticLibrary:'''),
    ('''        self._voices: list[list] = []          # [buffer, position]
        self._lock = threading.Lock()
        self.device_name = ""''',
     '''        self._voices: list[list] = []          # [buffer, position]
        self._sound: list[list] = []           # game sound on the controller speaker (channels 1/2)
        self.sound_gain = 0.5
        self._lock = threading.Lock()
        self.device_name = ""'''),
    ('''    def _callback(self, outdata, frames, _time, _status) -> None:
        outdata.fill(0)
        with self._lock:
            alive = []
            for v in self._voices:
                buf, pos = v
                chunk = buf[pos:pos + frames]
                outdata[:len(chunk), 2:4] += chunk * self.gain
                v[1] = pos + frames
                if v[1] < len(buf):
                    alive.append(v)
            self._voices = alive''',
     '''    def play_sound(self, buf: np.ndarray) -> None:
        with self._lock:
            self._sound.append([buf, 0])

    def _callback(self, outdata, frames, _time, _status) -> None:
        outdata.fill(0)
        with self._lock:
            self._voices = _mix_into(outdata[:, 2:4], self._voices, frames, self.gain)
            self._sound = _mix_into(outdata[:, 0:2], self._sound, frames, self.sound_gain)'''),
    ('''class RumbleHaptics:''',
     '''def _mix_into(out: np.ndarray, voices: list[list], frames: int, gain: float) -> list[list]:
    alive = []
    for v in voices:
        buf, pos = v
        chunk = buf[pos:pos + frames]
        out[:len(chunk)] += chunk * gain
        v[1] = pos + frames
        if v[1] < len(buf):
            alive.append(v)
    return alive


class SpeakerOut:
    """Game sounds on the PC's speakers/headphones (the default output, never the controller)."""

    def __init__(self) -> None:
        import sounddevice as sd
        self.gain = 0.5
        self._voices: list[list] = []
        self._lock = threading.Lock()
        dev, self.device_name = self._device(sd)
        self._stream = sd.OutputStream(device=dev, samplerate=SR, channels=2, dtype="float32", latency="low",
                                       callback=self._callback)
        self._stream.start()

    @staticmethod
    def _device(sd):
        default = sd.query_devices(kind="output")
        if "DualSense" not in default["name"]:
            return None, default["name"]
        for i, d in enumerate(sd.query_devices()):
            if d["max_output_channels"] >= 2 and "DualSense" not in d["name"] and d["hostapi"] == default["hostapi"]:
                return i, d["name"]
        raise RuntimeError("no speaker output found besides the controller")

    @property
    def latency_ms(self) -> float:
        return float(self._stream.latency) * 1000

    def play(self, buf: np.ndarray) -> None:
        with self._lock:
            self._voices.append([buf, 0])

    def _callback(self, outdata, frames, _time, _status) -> None:
        outdata.fill(0)
        with self._lock:
            self._voices = _mix_into(outdata, self._voices, frames, self.gain)
        np.clip(outdata, -1.0, 1.0, out=outdata)

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()


class RumbleHaptics:'''),
])

edit("runtime.py", [
    ("from ds5.haptics import AudioHaptics, Cue, HapticLibrary, RumbleHaptics",
     "from ds5.haptics import AudioHaptics, Cue, HapticLibrary, RumbleHaptics, SpeakerOut"),
    ('''        self.haptics_error = ""
        self.driver = StaticDriver()''',
     '''        self.haptics_error = ""
        self.sound_mode = "off"              # pc | controller | off
        self.sound_gain = 0.5
        self.sound_error = ""
        self.speaker: Optional[SpeakerOut] = None
        self.driver = StaticDriver()'''),
    ('''        if self.haptics:
            self.haptics.close()
            self.haptics = None

    # ---------- haptics ----------''',
     '''        if self.haptics:
            self.haptics.close()
            self.haptics = None
        if self.speaker:
            self.speaker.close()
            self.speaker = None

    # ---------- haptics ----------'''),
    ('''    @property
    def kick_delay_ms(self) -> float:''',
     '''    def set_sound(self, mode: str, gain: Optional[float] = None) -> None:
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
    def kick_delay_ms(self) -> float:'''),
    ('''    def play(self, cue: Cue | str | None) -> None:
        h = self.haptics
        if h and cue:
            h.play(Cue(cue) if isinstance(cue, str) else cue)''',
     '''    def play(self, cue: Cue | str | None) -> None:
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
                    h.play_sound(buf)'''),
])
print("sound patch applied")
