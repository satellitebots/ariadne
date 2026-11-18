"""Placeholder Ariadne marks: a labyrinth with a gold thread running to its centre.
Swap the PNGs in desktop/assets/ for real artwork any time; `ariadne desktop --build` picks them up.
Run: python desktop/make_icons.py"""
import math
from pathlib import Path

from PIL import Image, ImageDraw

OUT = Path(__file__).parent / "assets"
GOLD, INK, PAPER, NIGHT, STONE = (212, 166, 74), (26, 31, 38), (250, 248, 243), (13, 17, 23), (120, 130, 145)


def mark(size: int, bg, wall) -> Image.Image:
    s = 4  # supersample
    n = size * s
    im = Image.new("RGBA", (n, n), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle([0, 0, n - 1, n - 1], radius=int(n * 0.225), fill=bg)
    c = n / 2
    w = max(2, int(n * 0.028))
    for r, g in zip((0.36, 0.28, 0.20, 0.12), (90, 270, 90, 270)):  # rings open on alternating sides
        r *= n
        d.arc([c - r, c - r, c + r, c + r], start=g + 14, end=g + 360 - 14, fill=wall, width=w)
    # the thread: enters at the bottom, passes each gap, ends in the centre
    path = [(90, 0.44), (90, 0.36), (180, 0.32), (270, 0.28), (360, 0.24), (450, 0.20), (540, 0.16),
            (630, 0.12), (700, 0.06), (720, 0.0)]
    pts = []
    for (a0, r0), (a1, r1) in zip(path, path[1:]):
        for k in range(24):
            t = k / 24
            a, r = math.radians(a0 + (a1 - a0) * t), n * (r0 + (r1 - r0) * t)
            pts.append((c + r * math.cos(a), c + r * math.sin(a)))
    pts.append((c, c))
    d.line(pts, fill=GOLD, width=int(w * 0.9), joint="curve")
    d.ellipse([c - w * 1.4, c - w * 1.4, c + w * 1.4, c + w * 1.4], fill=GOLD)
    return im.resize((size, size), Image.LANCZOS)


def main():
    OUT.mkdir(exist_ok=True)
    dark = mark(1024, NIGHT, STONE)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    for name in ("icon", "icon-dark"):
        dark.save(OUT / f"{name}.png")
        dark.save(OUT / f"{name}.ico", sizes=sizes)
    mark(256, PAPER, INK).save(OUT / "mark-light.png")
    mark(256, NIGHT, STONE).save(OUT / "mark-dark.png")
    mark(180, PAPER, INK).save(OUT / "apple-touch-icon.png")
    print("wrote", ", ".join(sorted(p.name for p in OUT.iterdir())))


if __name__ == "__main__":
    main()
