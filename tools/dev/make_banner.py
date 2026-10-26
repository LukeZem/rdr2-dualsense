"""Mod page images: release/banner.png (1920x1080 main image) and release/features.png (feature card).
Western-poster look: worn paper, dark ink, a red-dead red accent, a drawn DualSense outline."""
import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

OUT = Path(__file__).resolve().parents[2] / "release"
FONTS = Path("C:/Windows/Fonts")
INK = (34, 22, 16)
RED = (150, 22, 18)
PAPER = (226, 205, 166)


def font(name, size):
    return ImageFont.truetype(str(FONTS / name), size)


def paper(w, h, seed=7):
    rnd = random.Random(seed)
    im = Image.new("RGB", (w, h), PAPER)
    px = im.load()
    for y in range(h):
        for x in range(0, w, 2):
            n = rnd.randint(-10, 10)
            c = tuple(max(0, min(255, v + n)) for v in PAPER)
            px[x, y] = c
            if x + 1 < w:
                px[x + 1, y] = c
    # vignette: burnt edges, light centre
    small = Image.new("L", (64, 36))
    for y in range(36):
        for x in range(64):
            r = math.hypot((x - 31.5) / 32, (y - 17.5) / 18)
            small.putpixel((x, y), int(255 * max(0.0, min(1.0, 1.25 - 0.75 * r ** 2.2))))
    vig = small.resize((w, h), Image.BICUBIC)
    im = Image.composite(im, Image.new("RGB", (w, h), (60, 32, 16)), vig)
    # stains
    st = Image.new("L", (w, h), 0)
    ds = ImageDraw.Draw(st)
    for _ in range(18):
        x, y, r = rnd.randint(0, w), rnd.randint(0, h), rnd.randint(40, 220)
        ds.ellipse([x - r, y - r, x + r, y + r], fill=rnd.randint(8, 22))
    st = st.filter(ImageFilter.GaussianBlur(40))
    im = Image.composite(Image.new("RGB", (w, h), (150, 110, 70)), im, st)
    return im


def centered(d, y, text, f, fill, w):
    tw = d.textlength(text, font=f)
    d.text(((w - tw) / 2, y), text, font=f, fill=fill)


def controller(d, cx, cy, s, col, width):
    """A DualSense outline: body, grips, touchpad, sticks, buttons, triggers."""
    def P(x, y):
        return (cx + x * s, cy + y * s)
    body = [P(-1.55, -0.35), P(-1.2, -0.62), P(-0.55, -0.7), P(0.55, -0.7), P(1.2, -0.62), P(1.55, -0.35),
            P(1.75, 0.35), P(1.85, 0.95), P(1.6, 1.25), P(1.25, 1.2), P(0.95, 0.7), P(0.45, 0.45),
            P(-0.45, 0.45), P(-0.95, 0.7), P(-1.25, 1.2), P(-1.6, 1.25), P(-1.85, 0.95), P(-1.75, 0.35)]
    d.line(body + [body[0]], fill=col, width=width, joint="curve")
    d.rounded_rectangle([P(-0.62, -0.62), P(0.62, -0.05)], radius=int(0.12 * s), outline=col, width=width)
    for x in (-0.55, 0.55):
        d.ellipse([P(x - 0.22, 0.05), P(x + 0.22, 0.49)], outline=col, width=width)
    for dx, dy in ((0, -0.2), (0, 0.2), (-0.2, 0), (0.2, 0)):
        x, y = 1.1 + dx, -0.12 + dy
        d.ellipse([P(x - 0.08, y - 0.08), P(x + 0.08, y + 0.08)], outline=col, width=max(2, width // 2))
    d.rectangle([P(-1.3, -0.24), P(-0.96, -0.12)], outline=col, width=max(2, width // 2))
    d.rectangle([P(-1.19, -0.35), P(-1.07, -0.01)], outline=col, width=max(2, width // 2))
    # triggers, with the "resistance" arcs
    for sx in (-1, 1):
        d.line([P(sx * 1.45, -0.62), P(sx * 1.3, -0.95), P(sx * 0.95, -0.95), P(sx * 0.9, -0.7)], fill=col, width=width)
        for k in range(3):
            r = (0.25 + 0.14 * k) * s
            x0, y0 = P(sx * 1.15, -1.0)
            d.arc([x0 - r, y0 - r, x0 + r, y0 + r], 200 if sx < 0 else 280, 260 if sx < 0 else 340, fill=RED, width=max(2, width // 2))


def banner():
    w, h = 1920, 1080
    im = paper(w, h)
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, w - 40, h - 40], outline=INK, width=6)
    d.rectangle([56, 56, w - 56, h - 56], outline=INK, width=2)
    centered(d, 90, "~  A MOD FOR RED DEAD REDEMPTION 2  ~", font("georgiab.ttf", 44), INK, w)
    centered(d, 160, "DUALSENSE", font("georgiab.ttf", 230), INK, w)
    centered(d, 410, "for  RDR2", font("georgiaz.ttf", 110), RED, w)
    controller(d, w / 2, 745, 135, INK, 9)
    centered(d, 920, "ADAPTIVE TRIGGERS  *  HAPTICS  *  VOICE & WHISTLE", font("georgiab.ttf", 50), INK, w)
    centered(d, 985, "every gun its own pull  -  every hoof on the real ground", font("georgiai.ttf", 38), INK, w)
    im.save(OUT / "banner.png")


def features():
    w, h = 1920, 1080
    im = paper(w, h, seed=11)
    d = ImageDraw.Draw(im)
    d.rectangle([40, 40, w - 40, h - 40], outline=INK, width=6)
    centered(d, 70, "WHAT YOU FEEL", font("georgiab.ttf", 110), INK, w)
    rows = [
        ("TRIGGERS", "Per-weapon pull, the shot on the break, hammer & lever on R2, recoil shove"),
        ("DEAD EYE", "Every painted target ticks, every shot of the volley kicks"),
        ("FISHING", "The bite tugs R2, the real line tension on L2, the fish fights left and right"),
        ("HORSE", "Real hoofbeats at every gait on the real ground - mud, gravel, wood, grass"),
        ("ON FOOT", "Arthur's footsteps, landings, ledges, doors, drawing and holstering"),
        ("CAMP LIFE", "Bites and sips, gun cleaning, brushing the horse, skinning, herbs, bathing"),
        ("HONOR", "A warm swell and gold glow when honor rises, a sinking thud when it falls"),
        ("VOICE", "Whistle to call your horse - say \"chao\" to greet a stranger for real"),
    ]
    fh, fb = font("georgiab.ttf", 46), font("georgia.ttf", 38)
    y = 230
    for head, text in rows:
        d.text((150, y), head, font=fh, fill=RED)
        d.text((520, y + 6), text, font=fb, fill=INK)
        d.line([(150, y + 76), (w - 150, y + 76)], fill=(120, 90, 60), width=1)
        y += 96
    im.save(OUT / "features.png")


if __name__ == "__main__":
    banner()
    features()
    print("banner.png, features.png ->", OUT)
