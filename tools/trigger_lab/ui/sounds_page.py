"""Sounds: listen to the game's own sounds and tell the lab what each one is.

Keyboard: ↑↓ select · Space play on speakers · H play as haptics · 1-9/0 assign role.
Roles feed the haptics: every sound labelled 'shot' in a weapon's bank is one of that
weapon's shot variants; 'explosion' sounds drive dynamite and cannons.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

import numpy as np

from ds5.haptics import Cue
from gameaudio import convert
from gameaudio.library import bank_kind
from . import theme as T
from .widgets import Waveform

QUICK_ROLES = ["shot", "shot_far", "cock", "lever_open", "lever_close", "bolt_open", "bolt_close",
               "pump_back", "pump_forward", "ignore"]
MORE_ROLES = ["reload", "shell", "dry_fire", "draw", "holster", "explosion", "impact", "other", "unknown"]
PREVIEW_PRESET = {"weapon": "handgun", "explosions": "explosion"}


class SoundsPage(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master)
        self.app = app
        self.ga = app.rt.game
        self.bank: str | None = None
        self.sounds = []
        self._speaker = None
        self._build()
        self._fill_banks()

    def _build(self) -> None:
        left = ttk.Frame(self, style="Panel.TFrame", padding=T.px(8))
        left.pack(side="left", fill="y")
        ttk.Label(left, text="Sound banks", style="H2.TLabel").pack(anchor="w")
        src = ", ".join(sorted(set(self.ga.sources.values()))) or "none found"
        ttk.Label(left, text=f"from: {src}", style="PanelMuted.TLabel", wraplength=T.px(240)).pack(anchor="w", pady=(T.px(0), T.px(6)))
        self.banks = ttk.Treeview(left, show="tree", height=26, selectmode="browse")
        self.banks.column("#0", width=T.px(250))
        self.banks.pack(fill="y", expand=True)
        self.banks.bind("<<TreeviewSelect>>", lambda _e: self._on_bank())

        mid = ttk.Frame(self, padding=(T.px(14), T.px(6)))
        mid.pack(side="left", fill="both", expand=True)
        self.title = ttk.Label(mid, style="Title.TLabel", text="Sounds")
        self.title.pack(anchor="w")
        self.used = ttk.Label(mid, style="Muted.TLabel", wraplength=T.px(700))
        self.used.pack(anchor="w")
        f = ttk.Frame(mid)
        f.pack(fill="x", pady=6)
        ttk.Label(f, text="filter").pack(side="left")
        self.filter = tk.StringVar()
        self.filter.trace_add("write", lambda *_: self._fill_sounds())
        ttk.Entry(f, textvariable=self.filter, width=20).pack(side="left", padx=6)
        self.max_len = tk.StringVar(value="any")
        ttk.Label(f, text="length").pack(side="left", padx=(10, 0))
        cb = ttk.Combobox(f, values=["any", "< 0.3 s", "< 0.6 s", "< 1.5 s", "> 1.5 s"], textvariable=self.max_len,
                          state="readonly", width=8)
        cb.pack(side="left", padx=6)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._fill_sounds())
        self.role_filter = tk.StringVar(value="all roles")
        rb = ttk.Combobox(f, values=["all roles"] + QUICK_ROLES + MORE_ROLES + ["shared"], textvariable=self.role_filter,
                          state="readonly", width=12)
        rb.pack(side="left")
        rb.bind("<<ComboboxSelected>>", lambda _e: self._fill_sounds())
        cols = ("name", "len", "loud", "role", "ch")
        self.list = ttk.Treeview(mid, columns=cols, show="headings", height=14, selectmode="browse")
        for c, label, w in zip(cols, ("sound", "length", "loudness", "role", "channels"), (240, 80, 90, 160, 80)):
            self.list.heading(c, text=label)
            self.list.column(c, width=T.px(w), anchor="w" if c in ("name", "role") else "center")
        self.list.pack(fill="x")
        self.list.bind("<<TreeviewSelect>>", lambda _e: self._on_sound())
        self.wave = Waveform(mid, width=700, height=150)
        self.wave.pack(anchor="w", pady=8)
        b = ttk.Frame(mid)
        b.pack(fill="x")
        ttk.Button(b, text="▶ speakers  [Space]", style="Accent.TButton", command=self.play_speakers).pack(side="left")
        ttk.Button(b, text="▶ haptics  [H]", command=self.play_haptic).pack(side="left", padx=6)
        ttk.Button(b, text="■ stop", command=self.stop).pack(side="left")
        ttk.Label(mid, text="What is it?  (keys 1-9, 0)", style="Muted.TLabel").pack(anchor="w", pady=(T.px(10), T.px(2)))
        roles = ttk.Frame(mid)
        roles.pack(fill="x")
        for i, r in enumerate(QUICK_ROLES):
            key = str((i + 1) % 10)
            ttk.Button(roles, text=f"{key} {r}", command=lambda r=r: self.assign(r)).grid(row=i // 5, column=i % 5,
                                                                                         sticky="ew", padx=2, pady=2)
        more = ttk.Frame(mid)
        more.pack(fill="x", pady=4)
        for r in MORE_ROLES:
            ttk.Button(more, text=r, command=lambda r=r: self.assign(r)).pack(side="left", padx=2)
        ttk.Label(mid, style="Muted.TLabel", wraplength=T.px(700), justify="left", text=(
            "Tip: in weapon banks the game picks one 'shot' at random per shot - leave all real shots as 'shot', "
            "mark distant/echo-only versions 'shot_far' so they are not used for the gun in your hands. "
            "Labels are saved to data/sound_labels.json and used immediately.")).pack(anchor="w", pady=8)
        for key in ("<space>", "h", "H") + tuple(str(i) for i in range(10)):
            self.bind_all(key, self._key, add="+")

    # ---------- lists ----------
    def _fill_banks(self) -> None:
        self.banks.delete(*self.banks.get_children())
        if not self.ga.available:
            self.title.config(text="No game sound banks found")
            self.used.config(text="Install a weapon sound mod in lml (e.g. RWS) or put exported .awc files in a folder.")
            return
        groups = {"weapon": "Weapons", "explosions": "Explosions", "resident": "Shared (mechanics, foley...)",
                  "other": "Other"}
        nodes = {k: self.banks.insert("", "end", iid=f"g:{k}", text=v, open=True) for k, v in groups.items()}
        for b in self.ga.banks():
            users = self._users(b)
            label = b if not users else f"{b}  ·  {users[0]}" + (f" +{len(users) - 1}" if len(users) > 1 else "")
            self.banks.insert(nodes[bank_kind(b)], "end", iid=b, text=label)
        for k, n in nodes.items():
            if not self.banks.get_children(n):
                self.banks.delete(n)
        first = self.ga.banks("weapon")
        if first:
            self.banks.selection_set(first[0])
            self.banks.see(first[0])

    def _users(self, bank: str) -> list[str]:
        return [w["label"] for w in self.app.catalog.weapons if w.get("bank") == bank]

    def _on_bank(self) -> None:
        sel = self.banks.selection()
        if not sel or sel[0].startswith("g:"):
            return
        self.bank = sel[0]
        self.app.status_busy(f"decoding {self.bank}...")
        self.sounds = self.ga.sounds(self.bank)
        self.app.status_busy("")
        users = self._users(self.bank)
        self.title.config(text=self.bank)
        self.used.config(text=(f"used by: {', '.join(users)}" if users else "not tied to a weapon")
                         + f"  ·  {len(self.sounds)} distinct sounds  ·  {self.ga.paths[self.bank]}")
        self._fill_sounds()

    def _fill_sounds(self) -> None:
        self.list.delete(*self.list.get_children())
        q = self.filter.get().lower()
        lim = self.max_len.get()
        rf = self.role_filter.get()
        for i, s in enumerate(self.sounds):
            secs = s.seconds
            if lim == "< 0.3 s" and secs >= 0.3 or lim == "< 0.6 s" and secs >= 0.6 \
                    or lim == "< 1.5 s" and secs >= 1.5 or lim == "> 1.5 s" and secs <= 1.5:
                continue
            role = self.ga.role(s)
            if rf != "all roles" and role != rf:
                continue
            if q and q not in s.label.lower() and q not in role:
                continue
            mark = "" if role == s.auto_role and f"{s.bank}/{s.key}" not in self.ga.labels else "  (yours)"
            self.list.insert("", "end", iid=str(i), values=(
                s.label, f"{secs:.2f} s", f"{s.feats.get('rms', 0):.3f}" if secs < 4 else "-",
                role + mark, "stereo" if s.stereo else "mono"))
        kids = self.list.get_children()
        if kids:
            self.list.selection_set(kids[0])

    def _current(self):
        sel = self.list.selection()
        return self.sounds[int(sel[0])] if sel else None

    def _on_sound(self) -> None:
        s = self._current()
        if not s:
            return
        data = s.data()
        preset = PREVIEW_PRESET.get(bank_kind(s.bank), "mech")
        hap = convert.to_haptic(data, s.rate, preset) if s.seconds < 6 else None
        self.wave.draw(data, s.rate, hap, f"{s.label} · {s.rate} Hz · {s.seconds:.2f} s · haptic preview: {preset}")

    # ---------- actions ----------
    def _key(self, ev) -> None:
        if self.app.page is not self or isinstance(ev.widget, (tk.Entry, ttk.Entry)):
            return
        if ev.keysym == "space":
            self.play_speakers()
        elif ev.keysym in ("h", "H"):
            self.play_haptic()
        elif ev.keysym.isdigit():
            idx = (int(ev.keysym) - 1) % 10
            self.assign(QUICK_ROLES[idx])

    def play_speakers(self) -> None:
        s = self._current()
        if not s:
            return
        import sounddevice as sd
        dev = self._speaker_device(sd)
        try:
            sd.play(s.data(), s.rate, device=dev)
        except Exception as e:
            self.app.log(f"speaker playback failed: {e}")

    @staticmethod
    def _speaker_device(sd):
        """The default output, unless that is the controller itself."""
        try:
            default = sd.query_devices(kind="output")
            if "DualSense" not in default["name"]:
                return None
            for i, d in enumerate(sd.query_devices()):
                if d["max_output_channels"] >= 2 and "DualSense" not in d["name"] and d["hostapi"] == default["hostapi"]:
                    return i
        except Exception:
            pass
        return None

    def play_haptic(self) -> None:
        s = self._current()
        if not s or not self.app.rt.haptics:
            return
        preset = PREVIEW_PRESET.get(bank_kind(s.bank), "mech")
        buf = convert.to_haptic(s.data()[: int(s.rate * 3)], s.rate, preset)
        lib = self.app.rt.library
        lib.buffers["_preview"] = [buf]
        self.app.rt.play(Cue("_preview"))

    def stop(self) -> None:
        import sounddevice as sd
        sd.stop()

    def assign(self, role: str) -> None:
        s = self._current()
        if not s:
            return
        self.ga.set_role(s, role)
        sel = self.list.selection()
        # weapons using this bank rebuild their shot haptics from the new labels
        for w in self.app.catalog.weapons:
            if w.get("bank") == s.bank:
                self.app.rt.library.buffers.pop(f"{w['name']}:shot", None)
        if bank_kind(s.bank) == "explosions":
            self.app.rt.library.reload()
        self.app.pages["range"]._rebuild()
        self._fill_sounds()
        if sel and self.list.exists(sel[0]):
            nxt = self.list.next(sel[0]) or sel[0]
            self.list.selection_set(nxt)
            self.list.see(nxt)
        self.app.log(f"{s.bank}/{s.label} = {role}")

    def on_show(self) -> None:
        self.app.set_driver(self, None)

    def tick(self) -> None:
        pass
