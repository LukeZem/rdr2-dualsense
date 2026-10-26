"""DualSense Trigger Lab - feel and tune every RDR2 weapon outside the game.

Run:  run_lab.bat   (or ..\\..\\.venv\\Scripts\\python.exe lab.py)
Close DSX / DS4Windows and the game first: they overwrite trigger effects.
"""
from __future__ import annotations

import sys
import time
import tkinter as tk
from pathlib import Path
from tkinter import ttk

from ds5.device import find_conflicting_processes
from runtime import Runtime
from sim.catalog import Catalog
from sim.engine import Calibration, StaticDriver
from ui import theme as T
from ui.other_pages import CalibratePage, HapticsPage, LabPage, LogPage
from ui.range_page import RangePage
from ui.sounds_page import SoundsPage
from ui.widgets import Chip

BASE = Path(__file__).resolve().parent
NAV = [("range", "🎯  Weapon Range"), ("sounds", "🔊  Sounds"), ("lab", "🧪  Effect Lab"),
       ("calibrate", "📏  Calibrate"), ("haptics", "〰  Haptics"), ("log", "📄  Log")]


class App:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("RDR2 · DualSense Trigger Lab")
        sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
        root.geometry(f"{int(sw * 0.86)}x{int(sh * 0.86)}+{int(sw * 0.07)}+{int(sh * 0.05)}")
        T.apply(root)
        self._log_buffer: list[str] = []
        self.calib_path = BASE / "data" / "calibration.json"
        self.calib = Calibration.load(self.calib_path)
        self.catalog = Catalog(BASE / "data" / "weapons.json")
        self.rt = Runtime(BASE)
        self.page = None
        self._last_chips = 0.0

        header = tk.Frame(root, bg=T.PANEL, height=T.px(52))
        header.pack(fill="x")
        tk.Label(header, text="RDR2", bg=T.PANEL, fg=T.ACCENT, font=("Segoe UI Black", 16)).pack(side="left", padx=(T.px(16), T.px(4)))
        tk.Label(header, text="DualSense Trigger Lab", bg=T.PANEL, fg=T.FG, font=("Segoe UI Semibold", 14)).pack(side="left")
        self.chips = {k: Chip(header) for k in ("busy", "warn", "audio", "calib", "haptics", "pad")}
        for c in self.chips.values():
            c.pack(side="right", padx=T.px(4), pady=T.px(10))
        self.chips["calib"].bind("<Button-1>", lambda _e: self.show("calibrate"))
        self.chips["calib"].config(cursor="hand2")

        body = tk.Frame(root, bg=T.BG)
        body.pack(fill="both", expand=True)
        nav = tk.Frame(body, bg=T.PANEL, width=T.px(200))
        nav.pack(side="left", fill="y")
        nav.pack_propagate(False)
        self.nav_items: dict[str, tk.Label] = {}
        for key, text in NAV:
            lbl = tk.Label(nav, text=text, bg=T.PANEL, fg=T.FG, font=("Segoe UI", 11), anchor="w", padx=T.px(18), pady=T.px(10),
                           cursor="hand2")
            lbl.pack(fill="x")
            lbl.bind("<Button-1>", lambda _e, k=key: self.show(k))
            self.nav_items[key] = lbl
        self.content = tk.Frame(body, bg=T.BG)
        self.content.pack(side="left", fill="both", expand=True)

        self.pages = {"log": LogPage(self.content, self)}
        for msg in self._log_buffer:
            self.pages["log"].write(msg)
        self._connect()
        self.pages.update(range=RangePage(self.content, self), sounds=SoundsPage(self.content, self),
                          lab=LabPage(self.content, self), calibrate=CalibratePage(self.content, self),
                          haptics=HapticsPage(self.content, self))
        start = sys.argv[sys.argv.index("--page") + 1] if "--page" in sys.argv else None
        self.show(start if start in self.pages else "range" if self.calib.calibrated else "calibrate")
        root.protocol("WM_DELETE_WINDOW", self.quit)
        self._tick()

    # ---------- plumbing ----------
    def log(self, msg: str) -> None:
        line = time.strftime("%H:%M:%S  ") + msg
        if "log" in getattr(self, "pages", {}):
            self.pages["log"].write(line)
        else:
            self._log_buffer.append(line)

    def status_busy(self, text: str) -> None:
        self.chips["busy"].set(text, T.ACCENT)
        self.root.update_idletasks()

    def set_driver(self, page, driver) -> None:
        if page is self.page:
            self.rt.driver = driver or StaticDriver()

    def on_haptics_changed(self) -> None:
        self.pages["range"]._rebuild()

    def show(self, key: str) -> None:
        if self.page is not None:
            self.page.pack_forget()
        self.page = self.pages[key]
        self.page.pack(fill="both", expand=True)
        for k, lbl in self.nav_items.items():
            lbl.config(bg=T.PANEL2 if k == key else T.PANEL, fg=T.ACCENT if k == key else T.FG)
        self.page.on_show()

    def _connect(self) -> None:
        conflicts = find_conflicting_processes()
        if conflicts:
            self.chips["warn"].set("close " + ", ".join(c.replace(".exe", "") for c in conflicts), T.BAD)
        try:
            self.rt.connect()
            self.rt.set_haptics("audio" if self.rt.ds.transport == "USB" else "rumble")
            self.rt.set_sound("pc", 0.5)
            self.log(f"connected: {self.rt.ds.name} via {self.rt.ds.transport}; haptics {self.rt.haptics_mode}")
        except Exception as e:
            self.log(f"not connected: {e}")
        ga = self.rt.game
        self.log(f"game: {self.rt.game_dir or 'not found'}; sound banks: {len(ga.banks())} "
                 f"from {', '.join(sorted(set(ga.sources.values()))) or '-'}")

    def quit(self) -> None:
        try:
            self.rt.close()
        finally:
            self.root.destroy()

    # ---------- loop ----------
    def _tick(self) -> None:
        try:
            self._update()
        except Exception as e:                      # never let the UI loop die
            self.log(f"ui error: {e!r}")
        self.root.after(33, self._tick)

    def _update(self) -> None:
        now = time.monotonic()
        if now - self._last_chips > 0.5:
            self._last_chips = now
            rt = self.rt
            if rt.connected:
                ds = rt.ds
                err = f" · {ds.error}" if ds.error else ""
                self.chips["pad"].set(f"{ds.name} {ds.transport} · {ds.report_rate:.0f} Hz · battery "
                                      f"{rt.state.battery * 10}%{err}", T.BAD if err else T.GOOD)
            else:
                self.chips["pad"].set("controller not connected", T.BAD)
            h = rt.haptics
            self.chips["haptics"].set(f"haptics {rt.haptics_mode}" + (f" {h.latency_ms:.0f} ms" if rt.haptics_mode == "audio" and h else ""),
                                      T.GOOD if h else T.WARN)
            self.chips["calib"].set("calibrated" if self.calib.calibrated else "calibrate R2 ▸",
                                    T.GOOD if self.calib.calibrated else T.WARN)
            n = len(rt.game.banks("weapon"))
            self.chips["audio"].set(f"game audio: {n} weapon banks" if n else "game audio: none (synth only)",
                                    T.GOOD if n else T.WARN)
        self.page.tick()
        for _ in range(300):
            try:
                ev = self.rt.events.get_nowait()
            except Exception:
                break
            self.pages["range"].on_event(ev)
            self.pages["calibrate"].on_event(ev)
            if ev["type"] in ("dry", "calibrated_zone", "calibration_done"):
                self.log(str({k: v for k, v in ev.items() if k != "t"}))


def main() -> None:
    try:                                            # crisp text on scaled displays
        import ctypes
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except (AttributeError, OSError):
        pass
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
