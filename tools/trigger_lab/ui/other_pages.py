"""Effect Lab, Calibrate, Haptics and Log pages."""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from ds5 import effects
from ds5.device import OutputState
from ds5.haptics import AudioHaptics, Cue
from sim.calibrate import Calibrator
from sim.engine import Calibration, StaticDriver
from . import theme as T
from .widgets import TravelPlot, TriggerChart, ZoneEditor

MODE_HELP = {
    "Off": "No effect.",
    "Feedback": "Constant resistance from a zone to the end of travel.",
    "Slope Feedback": "Resistance ramping between two zones - a stacking pull (double action, bow draw).",
    "Weapon": "Sony's gun trigger: resistance from start to end zone, then it snaps. start 2-7, end > start.",
    "Bow": "Resistance from start to end zone, then the trigger is pushed back (snap force).",
    "Galloping": "Two-beat pulse (hooves) between start and end zone. Frequency in Hz.",
    "Vibration": "Trigger vibrates from a zone on - used for recoil kicks. Frequency in Hz.",
    "Machine": "Vibration alternating between amplitude A and B every period x 0.1 s.",
    "Zone Feedback (custom curve)": "Any pull curve: force per zone. A strong zone followed by a free one = a break.",
    "Zone Vibration (custom curve)": "Vibration amplitude per zone.",
    "Raw hex": "Send any 11 bytes (mode + 10 params) to explore undocumented modes.",
}


class LabPage(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=(T.px(14), T.px(6)))
        self.app = app
        self.driver = StaticDriver()
        self.vars: dict[str, tk.IntVar] = {}
        ttk.Label(self, text="Effect Lab", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, text="Raw adaptive-trigger effects - feel what the hardware can do.",
                  style="Muted.TLabel").pack(anchor="w")
        top = ttk.Frame(self)
        top.pack(fill="x", pady=8)
        self.target = tk.StringVar(value="R2")
        for t in ("R2", "L2", "Both"):
            ttk.Radiobutton(top, text=t, value=t, variable=self.target, style="Bg.TRadiobutton",
                            command=self.apply).pack(side="left")
        self.mode = tk.StringVar(value="Zone Feedback (custom curve)")
        cb = ttk.Combobox(top, values=list(effects.PARAMS) + list(effects.ZONE_MODES) + ["Raw hex"],
                          textvariable=self.mode, state="readonly", width=30)
        cb.pack(side="left", padx=12)
        cb.bind("<<ComboboxSelected>>", lambda _e: self._build_params())
        ttk.Button(top, text="All off", command=self.all_off).pack(side="left")
        self.help = ttk.Label(self, style="Muted.TLabel", wraplength=T.px(900))
        self.help.pack(anchor="w")
        self.params = ttk.Frame(self, style="Panel.TFrame", padding=T.px(8))
        self.params.pack(fill="x", pady=6)
        self.result = ttk.Label(self, font=T.MONO)
        self.result.pack(anchor="w")
        self.chart = TriggerChart(self, width=760)
        self.chart.pack(anchor="w", pady=6)
        self.plot = TravelPlot(self, width=760)
        self.plot.pack(anchor="w")
        self.fb = ttk.Label(self, font=T.MONO, style="Muted.TLabel")
        self.fb.pack(anchor="w", pady=4)
        self.zones_init = [0, 0, 1, 6, 7, 0, 0, 0, 0, 0]
        self.raw = tk.StringVar(value="21 FF 03 00 00 00 00 00 00 00 00")
        self._build_params()

    def _build_params(self) -> None:
        for w in self.params.winfo_children():
            w.destroy()
        mode = self.mode.get()
        self.help.config(text=MODE_HELP.get(mode, "Old-firmware effect with raw 0-255 positions. Experimental - "
                                                   "current firmware may ignore it."))
        self.vars = {}
        if mode == "Raw hex":
            ttk.Entry(self.params, textvariable=self.raw, width=50, font=T.MONO).pack(side="left")
            ttk.Button(self.params, text="Send", command=self.apply).pack(side="left", padx=6)
            self.apply()
            return
        specs = effects.ZONE_MODES[mode][1] if mode in effects.ZONE_MODES else effects.PARAMS[mode][1]
        for name, lo, hi, default in specs:
            row = ttk.Frame(self.params, style="Panel.TFrame")
            row.pack(fill="x")
            ttk.Label(row, text=name, width=16, style="Panel.TLabel").pack(side="left")
            var = tk.IntVar(value=default)
            T.scale(row, from_=lo, to=hi, orient="horizontal", variable=var, length=500,
                    command=lambda _v: self.apply()).pack(side="left")
            self.vars[name] = var
        if mode in effects.ZONE_MODES:
            row = ttk.Frame(self.params, style="Panel.TFrame")
            row.pack(fill="x", pady=4)
            self.zones = ZoneEditor(row, lambda _z: self.apply(), width=420, height=160)
            self.zones.pack(side="left")
            self.zones.set(self.zones_init)
            pre = ttk.Frame(row, style="Panel.TFrame")
            pre.pack(side="left", padx=16)
            for label, z in (("SA revolver", (0, 0, 1, 6, 7, 0, 0, 0, 0, 0)),
                             ("DA stacking", (0, 2, 3, 4, 5, 6, 7, 8, 0, 0)),
                             ("Two-stage rifle", (0, 1, 1, 1, 1, 2, 8, 0, 0, 0)),
                             ("Heavy shotgun", (0, 0, 1, 2, 8, 8, 0, 0, 0, 0)),
                             ("Wall only", (0, 0, 0, 0, 8, 0, 0, 0, 0, 0)), ("Clear", (0,) * 10)):
                ttk.Button(pre, text=label, command=lambda z=z: (self.zones.set(list(z)), self.apply())).pack(fill="x", pady=1)
        self.apply()

    def block(self) -> bytes:
        mode = self.mode.get()
        if mode == "Raw hex":
            return effects.raw(bytes.fromhex(self.raw.get().replace(",", " ")))
        params = {k: v.get() for k, v in self.vars.items()}
        if mode in effects.ZONE_MODES:
            self.zones_init = self.zones.get()
            return effects.ZONE_MODES[mode][0](self.zones.get(), **params)
        return effects.PARAMS[mode][0](**params)

    def apply(self) -> None:
        try:
            b = self.block()
        except (ValueError, KeyError) as e:
            self.result.config(text=f"invalid: {e}", foreground=T.BAD)
            return
        out = OutputState(r2=self.driver.out.r2, l2=self.driver.out.l2)
        if self.target.get() in ("R2", "Both"):
            out.r2 = b
        if self.target.get() in ("L2", "Both"):
            out.l2 = b
        self.driver.out = out
        self.result.config(text=effects.describe(b), foreground=T.FG)

    def all_off(self) -> None:
        self.driver.out = OutputState()

    def on_show(self) -> None:
        self.app.set_driver(self, self.driver)

    def tick(self) -> None:
        rt, s = self.app.rt, self.app.rt.state
        out = self.driver.out
        self.chart.draw(self.app.calib.r2, out.r2, s.r2, out.l2, s.l2, self.app.calib.l2, [], [], 0)
        self.plot.draw(list(rt.history), [], [])
        self.fb.config(text=f"controller reports:  R2 feedback 0x{s.r2_feedback:02X} (stop {s.r2_feedback & 15}, "
                            f"status {s.r2_feedback >> 4})   L2 feedback 0x{s.l2_feedback:02X}   "
                            f"active effects 0x{s.effect_state:02X}  (R2 type {s.effect_state & 15})")


class CalibratePage(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=(T.px(14), T.px(6)))
        self.app = app
        self.cal: Calibrator | None = None
        ttk.Label(self, text="Calibrate", style="Title.TLabel").pack(anchor="w")
        ttk.Label(self, wraplength=T.px(900), justify="left", text=(
            "Measures where each of the 10 effect zones starts on YOUR controller, so the shot fires exactly at "
            "the break. A wall appears for every zone: pull gently until the trigger stops, hold still ~0.3 s, "
            "the wall disappears, release. 9 walls per trigger - about a minute.")).pack(anchor="w", pady=6)
        row = ttk.Frame(self)
        row.pack(fill="x", pady=6)
        self.trigger = tk.StringVar(value="r2")
        ttk.Radiobutton(row, text="R2", value="r2", variable=self.trigger, style="Bg.TRadiobutton").pack(side="left")
        ttk.Radiobutton(row, text="L2", value="l2", variable=self.trigger, style="Bg.TRadiobutton").pack(side="left")
        ttk.Button(row, text="Start", style="Accent.TButton", command=self.start).pack(side="left", padx=10)
        ttk.Button(row, text="Cancel", command=self.cancel).pack(side="left")
        ttk.Button(row, text="Reset to defaults", command=self.reset).pack(side="left", padx=20)
        self.msg = tk.Label(self, font=("Segoe UI Semibold", 16), bg=T.BG, fg=T.ACCENT, wraplength=T.px(900), justify="left")
        self.msg.pack(anchor="w", pady=14)
        self.progress = ttk.Progressbar(self, length=500, maximum=9)
        self.progress.pack(anchor="w")
        self.chart = TriggerChart(self, width=760)
        self.chart.pack(anchor="w", pady=10)
        self.table = ttk.Label(self, font=T.MONO)
        self.table.pack(anchor="w")
        self.show_table()

    def show_table(self) -> None:
        c = self.app.calib
        state = "measured" if c.calibrated else "DEFAULT ESTIMATE - not calibrated yet"
        self.table.config(text=(f"zone start raw ({state})\n     " + "".join(f"z{i:<4}" for i in range(10)) +
                                "\nR2   " + "".join(f"{v:<5}" for v in c.r2) +
                                "\nL2   " + "".join(f"{v:<5}" for v in c.l2)))

    def start(self) -> None:
        self.cal = Calibrator(self.trigger.get())
        self.app.set_driver(self, self.cal)

    def cancel(self) -> None:
        self.cal = None
        self.app.set_driver(self, StaticDriver())
        self.msg.config(text="Cancelled.")

    def reset(self) -> None:
        self.app.calib = Calibration()
        if self.app.calib_path.exists():
            self.app.calib_path.unlink()
        self.show_table()

    def on_show(self) -> None:
        self.app.set_driver(self, self.cal if self.cal and not self.cal.done else StaticDriver())
        if not self.cal:
            self.msg.config(text="Press Start, then follow the instructions here.")

    def tick(self) -> None:
        s, rt = self.app.rt.state, self.app.rt
        out = rt.frame.out if rt.frame else OutputState()
        if self.cal:
            self.msg.config(text=self.cal.message)
            self.progress.config(value=self.cal.zone - 1 + (1 if self.cal.done else 0))
        self.chart.draw(self.app.calib.r2, out.r2, s.r2, out.l2, s.l2, self.app.calib.l2, [], [], 0)

    def on_event(self, ev: dict) -> None:
        if ev["type"] == "calibration_done" and ev["ok"]:
            c = self.app.calib
            if ev["trigger"] == "r2":
                c.r2 = ev["table"]
            else:
                c.l2 = ev["table"]
            c.calibrated = True
            c.save(self.app.calib_path)
            self.show_table()
            self.app.log(f"calibration {ev['trigger'].upper()} saved: {ev['table']}")


class HapticsPage(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=(T.px(14), T.px(6)))
        self.app = app
        ttk.Label(self, text="Haptics", style="Title.TLabel").pack(anchor="w")
        row = ttk.Frame(self)
        row.pack(fill="x", pady=6)
        self.mode = tk.StringVar(value=app.rt.haptics_mode)
        self.exclusive = tk.BooleanVar(value=False)
        for label, value in (("Audio haptics (USB)", "audio"), ("Rumble emulation (Bluetooth)", "rumble"), ("Off", "off")):
            ttk.Radiobutton(row, text=label, value=value, variable=self.mode, style="Bg.TRadiobutton",
                            command=self.apply).pack(side="left", padx=(0, 10))
        ttk.Checkbutton(row, text="WASAPI exclusive (lower latency)", variable=self.exclusive, style="Bg.TCheckbutton",
                        command=self.apply).pack(side="left", padx=10)
        self.status = ttk.Label(self, style="Muted.TLabel")
        self.status.pack(anchor="w")
        g = ttk.Frame(self)
        g.pack(fill="x", pady=6)
        ttk.Label(g, text="master strength %").pack(side="left")
        self.gain = tk.IntVar(value=100)
        T.scale(g, from_=0, to=200, orient="horizontal", variable=self.gain, length=300, resolution=5, bg=T.BG,
                command=lambda _v: self._gain()).pack(side="left", padx=8)
        cols = ("name", "source", "variants")
        self.list = ttk.Treeview(self, columns=cols, show="headings", height=20)
        for c, label, w in zip(cols, ("recipe", "built from", "variants"), (280, 420, 80)):
            self.list.heading(c, text=label)
            self.list.column(c, width=T.px(w), anchor="w" if c != "variants" else "center")
        self.list.pack(anchor="w", pady=6)
        self.list.bind("<Double-Button-1>", lambda _e: self.play())
        b = ttk.Frame(self)
        b.pack(fill="x")
        ttk.Button(b, text="▶ play (double-click)", style="Accent.TButton", command=self.play).pack(side="left")
        ttk.Button(b, text="Reload haptics.json", command=self.reload).pack(side="left", padx=6)
        ttk.Label(self, style="Muted.TLabel", wraplength=T.px(900), justify="left", text=(
            "Weapon shots (WEAPON_...:shot) are built from that weapon's own recorded shots in the game's "
            "sound bank, converted for the actuators, plus a synthesized recoil thump. Other recipes live in "
            "data/haptics.json - edit, reload, feel.")).pack(anchor="w", pady=8)
        self.fill()

    def fill(self) -> None:
        lib = self.app.rt.library
        self.list.delete(*self.list.get_children())
        for n in lib.names():
            if not n.startswith("_"):
                self.list.insert("", "end", iid=n, values=(n, lib.source.get(n, ""), lib.variant_count(n)))

    def apply(self) -> None:
        self.app.rt.set_haptics(self.mode.get(), self.exclusive.get())
        self.mode.set(self.app.rt.haptics_mode)
        self._gain()
        self.app.on_haptics_changed()

    def _gain(self) -> None:
        if self.app.rt.haptics:
            self.app.rt.haptics.gain = self.gain.get() / 100

    def play(self) -> None:
        sel = self.list.selection()
        if sel:
            self.app.rt.play(Cue(sel[0]))

    def reload(self) -> None:
        try:
            self.app.rt.library.reload()
            self.fill()
            self.app.on_haptics_changed()
            self.app.log("haptics.json reloaded")
        except Exception as e:
            self.app.log(f"haptics.json error: {e}")

    def on_show(self) -> None:
        self.fill()

    def tick(self) -> None:
        rt = self.app.rt
        h = rt.haptics
        self.status.config(text=rt.haptics_error or (
            f"{h.device_name} · latency {h.latency_ms:.1f} ms · trigger recoil waits {rt.kick_delay_ms:.0f} ms "
            f"to land with it" if isinstance(h, AudioHaptics) else (h.device_name if h else "off")))


class LogPage(ttk.Frame):
    def __init__(self, master, app) -> None:
        super().__init__(master, padding=(T.px(14), T.px(6)))
        self.app = app
        ttk.Label(self, text="Log", style="Title.TLabel").pack(anchor="w")
        row = ttk.Frame(self)
        row.pack(fill="x", pady=6)
        self.rec = ttk.Button(row, text="● Record CSV trace", command=self.toggle)
        self.rec.pack(side="left")
        ttk.Button(row, text="Clear", command=lambda: self.text.delete("1.0", "end")).pack(side="left", padx=6)
        self.text = tk.Text(self, height=30, font=T.MONO, bg=T.PANEL, fg=T.FG, insertbackground=T.FG, bd=0)
        self.text.pack(fill="both", expand=True)

    def write(self, msg: str) -> None:
        self.text.insert("end", msg + "\n")
        self.text.see("end")

    def toggle(self) -> None:
        rt = self.app.rt
        if rt._csv:
            rt.stop_recording()
            self.rec.config(text="● Record CSV trace")
            self.write(f"saved {rt.recording_path}")
        else:
            self.write(f"recording to {rt.start_recording()}")
            self.rec.config(text="■ Stop recording")

    def on_show(self) -> None:
        pass

    def tick(self) -> None:
        pass
