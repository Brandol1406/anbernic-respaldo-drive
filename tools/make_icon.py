"""Draws 240x180 APPS icons in the same transparent style. Usage: python3 make_icon.py <kind> <out.png>"""
import math
import sys

from PIL import Image, ImageDraw

W, H = 240, 180
BLUE, GREEN, YELLOW, DARK, WHITE = (40, 110, 220, 255), (60, 170, 90, 255), (230, 200, 90, 255), (30, 30, 40, 255), (235, 235, 235, 255)


def monitor(d):
    # gauge: arc with needle + small battery
    cx, cy, r = 120, 110, 72
    d.pieslice((cx - r, cy - r, cx + r, cy + r), 180, 360, fill=BLUE)
    d.pieslice((cx - r + 16, cy - r + 16, cx + r - 16, cy + r - 16), 180, 360, fill=DARK)
    for i, col in enumerate((GREEN, YELLOW, (210, 60, 60, 255))):
        d.arc((cx - r + 4, cy - r + 4, cx + r - 4, cy + r - 4), 180 + i * 60, 240 + i * 60, fill=col, width=10)
    a = math.radians(225)
    d.line((cx, cy, cx + 50 * math.cos(a), cy + 50 * math.sin(a)), fill=WHITE, width=6)
    d.ellipse((cx - 8, cy - 8, cx + 8, cy + 8), fill=WHITE)
    d.rounded_rectangle((70, 130, 170, 160), 6, outline=WHITE, width=4)
    d.rectangle((170, 139, 177, 151), fill=WHITE)
    d.rectangle((78, 137, 140, 153), fill=GREEN)


def cloud(d):
    # cloud with up/down arrows
    d.ellipse((40, 70, 120, 150), fill=BLUE)
    d.ellipse((85, 40, 175, 130), fill=BLUE)
    d.ellipse((140, 80, 205, 145), fill=BLUE)
    d.rectangle((80, 110, 175, 150), fill=BLUE)
    d.polygon([(105, 75), (85, 100), (98, 100), (98, 130), (112, 130), (112, 100), (125, 100)], fill=WHITE)
    d.polygon([(150, 135), (130, 110), (143, 110), (143, 80), (157, 80), (157, 110), (170, 110)], fill=GREEN)


img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
{"monitor": monitor, "cloud": cloud}[sys.argv[1]](ImageDraw.Draw(img))
img.save(sys.argv[2])
