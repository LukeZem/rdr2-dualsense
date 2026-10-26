"""Dark theme for the lab (ttk 'clam' restyled)."""
import tkinter as tk
from tkinter import ttk

BG = "#15171b"
PANEL = "#1e2127"
PANEL2 = "#272b33"
LINE = "#343a44"
FG = "#e7e7e7"
MUTED = "#8b929d"
ACCENT = "#e3a33f"      # warm amber
GOOD = "#4cb36a"
WARN = "#e3a33f"
BAD = "#e0524f"
BLUE = "#4d93dc"

FONT = ("Segoe UI", 10)
SMALL = ("Segoe UI", 9)
BOLD = ("Segoe UI", 10, "bold")
TITLE = ("Segoe UI Semibold", 18)
H2 = ("Segoe UI Semibold", 12)
MONO = ("Consolas", 10)

S = 1.0                 # UI scale (physical px per logical px), set from the display DPI


def px(v: float) -> int:
    return int(round(v * S))


STATE_COLORS = {"ready": GOOD, "held": "#8a6d2f", "action": BLUE, "cycling": BLUE, "reloading": "#9b59b6",
                "draw": ACCENT, "firing": BAD, "flying": MUTED, "tethered": ACCENT, "empty": BAD, "lab": MUTED}


def apply(root: tk.Tk) -> None:
    global S
    S = max(1.0, root.winfo_fpixels("1i") / 96.0)
    root.configure(bg=BG)
    s = ttk.Style(root)
    s.theme_use("clam")
    s.configure(".", background=BG, foreground=FG, fieldbackground=PANEL2, font=FONT, bordercolor=LINE,
                lightcolor=PANEL2, darkcolor=PANEL2, troughcolor=PANEL2, focuscolor=ACCENT,
                selectbackground=ACCENT, selectforeground="#111")
    for name, bg in (("TFrame", BG), ("Panel.TFrame", PANEL), ("Card.TFrame", PANEL2)):
        s.configure(name, background=bg)
    s.configure("TLabel", background=BG, foreground=FG)
    s.configure("Panel.TLabel", background=PANEL)
    s.configure("Muted.TLabel", background=BG, foreground=MUTED, font=SMALL)
    s.configure("PanelMuted.TLabel", background=PANEL, foreground=MUTED, font=SMALL)
    s.configure("Title.TLabel", background=BG, foreground=FG, font=TITLE)
    s.configure("H2.TLabel", background=PANEL, foreground=ACCENT, font=H2)
    s.configure("TButton", background=PANEL2, foreground=FG, padding=(px(10), px(5)), borderwidth=0)
    s.map("TButton", background=[("active", LINE), ("pressed", ACCENT)], foreground=[("pressed", "#111")])
    s.configure("Accent.TButton", background=ACCENT, foreground="#111", font=BOLD)
    s.map("Accent.TButton", background=[("active", "#f0b85a")])
    for w in ("TCheckbutton", "TRadiobutton"):
        s.configure(w, background=PANEL, foreground=FG, indicatorcolor=PANEL2, indicatorbackground=PANEL2,
                    indicatorsize=px(13), indicatormargin=(px(2), px(2), px(6), px(2)))
        s.map(w, indicatorcolor=[("selected", ACCENT)], background=[("active", PANEL)])
    s.configure("Bg.TCheckbutton", background=BG)
    s.configure("Bg.TRadiobutton", background=BG)
    s.configure("TCombobox", fieldbackground=PANEL2, background=PANEL2, foreground=FG, arrowcolor=FG)
    s.map("TCombobox", fieldbackground=[("readonly", PANEL2)], foreground=[("readonly", FG)])
    root.option_add("*TCombobox*Listbox.background", PANEL2)
    root.option_add("*TCombobox*Listbox.foreground", FG)
    root.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
    s.configure("TEntry", fieldbackground=PANEL2, foreground=FG, insertcolor=FG)
    s.configure("TSpinbox", fieldbackground=PANEL2, foreground=FG, arrowcolor=FG, background=PANEL2)
    s.configure("Treeview", background=PANEL, fieldbackground=PANEL, foreground=FG, rowheight=px(25), borderwidth=0)
    s.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "#111")])
    s.configure("Treeview.Heading", background=PANEL2, foreground=MUTED, font=SMALL, borderwidth=0)
    s.configure("Vertical.TScrollbar", background=PANEL2, troughcolor=PANEL, arrowcolor=MUTED, borderwidth=0,
                arrowsize=px(12))
    s.configure("TCombobox", arrowsize=px(12))
    s.configure("TSpinbox", arrowsize=px(10))
    s.configure("Horizontal.TProgressbar", background=ACCENT, troughcolor=PANEL2)


def scale(master, **kw):
    """Themed slider (ui.widgets.Slider) taking tk.Scale-like arguments."""
    from .widgets import Slider
    kw.pop("orient", None)
    return Slider(master, **kw)
