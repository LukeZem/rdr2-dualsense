"""Haptics: recipe synthesizer, game-audio conversion and output backends.

A recipe is a list of layers rendered to stereo buffers (left / right actuator):
    click  - a few cycles of a Hann-windowed sine: sharp mechanical tap
    tone   - decaying sine with optional frequency sweep: recoil thump, string ring
    noise  - band-limited noise burst with attack/decay: slides, rattles, blast body
    ref    - another recipe, delayed/scaled: sequences (lever cycle = open + close)
    game   - sounds from the game's own banks (bank + role), converted for the actuators;
             every matching sound becomes a variant, one is picked per play like the game does
Common keys: amp (0-1), delay_ms, pan (-1 = left actuator only, 0 = both, +1 = right only).
A recipe may carry "fallback" layers used when its game sounds are not available.

Weapon shots are built per weapon from that weapon's recorded shots (ensure_weapon).

Backends:
    AudioHaptics  - the DualSense USB audio device, channels 3/4 (true voice-coil haptics)
    RumbleHaptics - rumble emulation in the HID report (works over Bluetooth, coarser)
"""
from __future__ import annotations

import json
import random
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import numpy as np

from gameaudio import convert

SR = 48000
MAX_VARIANTS = 8


@dataclass
class Cue:
    name: str
    gain: float = 1.0
    variant: Optional[int] = None
    speed: float = 1.0
    pan: Optional[float] = None       # re-pan at play time (e.g. which fist punched)


def _pan_gains(pan: float) -> tuple[float, float]:
    return min(1.0, 1.0 - pan), min(1.0, 1.0 + pan)


def _place(buf: np.ndarray, layer: dict) -> np.ndarray:
    delay = int(SR * float(layer.get("delay_ms", 0)) / 1000)
    if delay:
        buf = np.vstack([np.zeros((delay, 2), np.float32), buf])
    return buf


def _mix(parts: list[np.ndarray]) -> np.ndarray:
    parts = [p for p in parts if len(p)]
    if not parts:
        return np.zeros((1, 2), np.float32)
    out = np.zeros((max(len(p) for p in parts), 2), np.float32)
    for p in parts:
        out[:len(p)] += p
    return out


def synth_layer(layer: dict) -> np.ndarray:
    kind = layer["type"]
    amp = float(layer.get("amp", 1.0))
    if kind == "click":
        hz = float(layer.get("hz", 250))
        n = max(2, int(SR * float(layer.get("cycles", 1)) / hz))
        t = np.arange(n) / SR
        mono = np.sin(2 * np.pi * hz * t) * np.hanning(n) * amp
    elif kind == "tone":
        hz0 = float(layer["hz"])
        hz1 = float(layer.get("to_hz", hz0))
        attack = float(layer.get("attack_ms", 1.0)) / 1000
        decay = float(layer.get("decay_ms", 50)) / 1000
        n = int(SR * (attack + 5 * decay))
        t = np.arange(n) / SR
        freq = hz1 + (hz0 - hz1) * np.exp(-t / max(decay, 1e-4))
        phase = 2 * np.pi * np.cumsum(freq) / SR
        env = np.where(t < attack, t / max(attack, 1e-6), np.exp(-(t - attack) / max(decay, 1e-4)))
        mono = np.sin(phase) * env * amp
    elif kind == "noise":
        lo, hi = float(layer.get("lo", 60)), float(layer.get("hi", 300))
        attack = float(layer.get("attack_ms", 0.5)) / 1000
        decay = float(layer.get("decay_ms", 30)) / 1000
        n = int(SR * (attack + 5 * decay))
        rng = np.random.default_rng(int(layer.get("seed", 7)))
        spec = np.fft.rfft(rng.standard_normal(n))
        f = np.fft.rfftfreq(n, 1 / SR)
        spec[(f < lo) | (f > hi)] = 0
        noise = np.fft.irfft(spec, n)
        noise /= max(1e-9, np.max(np.abs(noise)))
        t = np.arange(n) / SR
        env = np.where(t < attack, t / max(attack, 1e-6), np.exp(-(t - attack) / max(decay, 1e-4)))
        mono = noise * env * amp
    else:
        raise ValueError(f"unknown layer type {kind!r}")
    gl, gr = _pan_gains(float(layer.get("pan", 0.0)))
    return _place(np.stack([mono * gl, mono * gr], axis=1).astype(np.float32), layer)


def _respeed(buf: np.ndarray, speed: float) -> np.ndarray:
    n = int(len(buf) / speed)
    src = np.arange(n) * speed
    return np.stack([np.interp(src, np.arange(len(buf)), buf[:, c]) for c in (0, 1)], axis=1).astype(np.float32)


def _speaker_audio(sound) -> np.ndarray:
    """A game sound as 48 kHz stereo float32 for the speakers."""
    d = sound.data()
    return np.stack([convert.resample(d[:, c], sound.rate) for c in (0, 1)], axis=1)


class HapticLibrary:
    def __init__(self, path: Path, game=None) -> None:
        self.path = path
        self.game = game                       # gameaudio.library.GameAudio or None
        self.buffers: dict[str, list[np.ndarray]] = {}
        self.audio: dict[str, list[np.ndarray]] = {}      # the game recording behind each variant
        self.kicks: dict[str, list[list[int]]] = {}
        self.source: dict[str, str] = {}
        self.recipes: dict[str, dict] = {}
        self.reload()

    # ---------- recipes ----------
    def reload(self) -> None:
        recipes = json.loads(self.path.read_text(encoding="utf-8"))
        self.recipes = {k: v for k, v in recipes.items() if not k.startswith("_")}
        self.buffers, self.kicks, self.source, self.audio = {}, {}, {}, {}
        for name in self.recipes:
            self._render(name, 0)

    def _game_sounds(self, layer: dict) -> list:
        if not self.game or not self.game.available:
            return []
        sounds = self.game.variants(layer["bank"], layer.get("role", "shot"))
        if len(sounds) > MAX_VARIANTS:
            sounds = random.Random(layer["bank"]).sample(sounds, MAX_VARIANTS)
        return sounds

    def _render(self, name: str, depth: int) -> list[np.ndarray]:
        if name in self.buffers:
            return self.buffers[name]
        if depth > 4:
            raise ValueError(f"recipe {name}: references nest too deep")
        recipe = self.recipes[name]
        static, variants, src = [], [], "synth"
        for layer in recipe["layers"]:
            if layer["type"] == "game":
                sounds = self._game_sounds(layer)
                if sounds:
                    src = f"game {layer['bank']} x{len(sounds)}"
                    self.audio.setdefault(name, [_speaker_audio(s) for s in sounds])
                    pan, amp = float(layer.get("pan", 0)), float(layer.get("amp", 1))
                    variants.append([_place(convert.to_haptic(s.data(), s.rate, layer.get("convert", "mech"), pan, amp),
                                            layer) for s in sounds])
                elif recipe.get("fallback"):
                    static += [synth_layer(l) for l in recipe["fallback"]]
            elif layer["type"] == "ref":
                ref = self._render(layer["name"], depth + 1)
                static.append(_place(ref[0] * float(layer.get("amp", 1.0)), layer))
            else:
                static.append(synth_layer(layer))
        gain = float(recipe.get("gain", 1.0))
        count = max([len(v) for v in variants] or [1])
        out = []
        for i in range(count):
            parts = static + [v[i % len(v)] for v in variants]
            out.append(np.clip(_mix(parts) * gain, -1, 1).astype(np.float32))
        self.buffers[name] = out
        self.source[name] = src
        return out

    def ensure_weapon(self, profile: dict) -> Optional[str]:
        """Build '<weapon>:shot' from the weapon's own recorded shots + its class's synthesized
        recoil thump. Returns the recipe name, or None when the game audio is missing."""
        bank = profile.get("bank")
        audio = profile.get("audio", {})
        synth = profile.get("recoil", {}).get("haptic")
        if not bank or not self.game or bank not in self.game.paths:
            return None
        name = f"{profile['id']}:shot"
        if name in self.buffers:
            return name
        sounds = self.game.variants(bank, "shot")[:MAX_VARIANTS]
        if not sounds:
            return None
        preset, pan = audio.get("convert", "handgun"), float(audio.get("pan", 0.0))
        mix = float(audio.get("synth_mix", 0.4))
        thump = self._render(synth, 0)[0] * mix if synth in self.recipes else None
        step_ms = float(profile.get("recoil", {}).get("trigger", {}).get("step_ms", 16))
        bufs, kicks = [], []
        for s in sounds:
            h = convert.to_haptic(s.data(), s.rate, preset, pan, 1.0 - 0.3 * mix)
            bufs.append(np.clip(_mix([h, thump] if thump is not None else [h]), -1, 1).astype(np.float32))
            kicks.append(convert.kick_steps(s.data(), s.rate, step_ms))
        self.buffers[name], self.kicks[name] = bufs, kicks
        self.audio[name] = [_speaker_audio(s) for s in sounds]
        self.source[name] = f"game {bank} x{len(bufs)} + synth {synth}"
        return name

    def names(self) -> list[str]:
        return sorted(self.buffers)

    def variant_count(self, name: str) -> int:
        return len(self.buffers.get(name, []))

    def pick(self, cue: Cue) -> Cue:
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

    def get(self, cue: Cue) -> Optional[np.ndarray]:
        bufs = self.buffers.get(cue.name)
        if not bufs:
            return None
        i = cue.variant if cue.variant is not None and 0 <= cue.variant < len(bufs) else random.randrange(len(bufs))
        buf = bufs[i]
        if abs(cue.speed - 1.0) > 1e-3:                    # slow motion: longer and deeper
            buf = _respeed(buf, cue.speed)
        if cue.pan is not None:                            # re-pan: strongest channel, placed at cue.pan
            mono = buf[:, int(np.argmax(np.abs(buf).sum(axis=0)))]
            gl, gr = _pan_gains(cue.pan)
            buf = np.stack([mono * gl, mono * gr], axis=1)
        return buf.astype(np.float32) * cue.gain


class AudioHaptics:
    """Mixes recipe buffers into channels 3/4 of the DualSense's 4-channel audio device."""

    def __init__(self, library: HapticLibrary, exclusive: bool = False) -> None:
        import sounddevice as sd
        self._sd = sd
        self.library = library
        self.gain = 1.0
        self._voices: list[list] = []          # [buffer, position]
        self._sound: list[list] = []           # game sound on the controller speaker (channels 1/2)
        self.sound_gain = 0.5
        self._lock = threading.Lock()
        self.device_name = ""
        idx = self._find_device()
        extra = sd.WasapiSettings(exclusive=True) if exclusive else None
        self._stream = sd.OutputStream(device=idx, samplerate=SR, channels=4, dtype="float32",
                                       latency="low", callback=self._callback, extra_settings=extra)
        self._stream.start()

    def _find_device(self) -> int:
        sd = self._sd
        wasapi = [i for i, h in enumerate(sd.query_hostapis()) if "WASAPI" in h["name"]]
        for i, d in enumerate(sd.query_devices()):
            if "DualSense" in d["name"] and d["max_output_channels"] >= 4 and d["hostapi"] in wasapi:
                self.device_name = d["name"]
                return i
        raise RuntimeError("DualSense audio device not found (haptics need a USB connection)")

    @property
    def latency_ms(self) -> float:
        return float(self._stream.latency) * 1000

    def play(self, cue: Cue) -> None:
        buf = self.library.get(cue)
        if buf is not None:
            with self._lock:
                self._voices.append([buf, 0])

    def play_sound(self, buf: np.ndarray) -> None:
        with self._lock:
            self._sound.append([buf, 0])

    def _callback(self, outdata, frames, _time, _status) -> None:
        outdata.fill(0)
        with self._lock:
            self._voices = _mix_into(outdata[:, 2:4], self._voices, frames, self.gain)
            self._sound = _mix_into(outdata[:, 0:2], self._sound, frames, self.sound_gain)
        np.clip(outdata, -1.0, 1.0, out=outdata)

    def close(self) -> None:
        self._stream.stop()
        self._stream.close()


def _mix_into(out: np.ndarray, voices: list[list], frames: int, gain: float) -> list[list]:
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


class RumbleHaptics:
    """Approximates recipes with the two rumble-emulation motors (Bluetooth fallback).
    tick() is called from the controller I/O thread and returns (left, right) 0-255."""

    STEP = 0.004

    def __init__(self, library: HapticLibrary) -> None:
        self.library = library
        self.gain = 1.0
        self.device_name = "rumble emulation"
        self._voices: list[list] = []          # [envelope (n,2), start_time]
        self._lock = threading.Lock()
        self.latency_ms = 0.0

    def _envelope(self, buf: np.ndarray) -> np.ndarray:
        hop = int(SR * self.STEP)
        n = len(buf) // hop + 1
        pad = np.zeros((n * hop, 2), np.float32)
        pad[:len(buf)] = np.abs(buf)
        return pad.reshape(n, hop, 2).max(axis=1)

    def play(self, cue: Cue, now: Optional[float] = None) -> None:
        buf = self.library.get(cue)
        if buf is not None:
            with self._lock:
                self._voices.append([self._envelope(buf), now if now is not None else time.perf_counter()])

    def tick(self, now: float) -> tuple[int, int]:
        left = right = 0.0
        with self._lock:
            alive = []
            for env, t0 in self._voices:
                i = int((now - t0) / self.STEP)
                if i < len(env):
                    l, r = env[i] * self.gain
                    left, right = max(left, l), max(right, r)
                    alive.append([env, t0])
            self._voices = alive
        # left motor = heavy low-frequency weight, right = light high-frequency weight
        return min(255, int(left * 255)), min(255, int(right * 200))

    def close(self) -> None:
        pass
