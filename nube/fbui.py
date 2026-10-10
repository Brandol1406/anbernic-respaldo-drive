"""Tiny framebuffer UI helpers for Anbernic stock OS apps (720x480, Pillow, /dev/fb0).

Same approach as the stock Clock app, plus the fix for the double-buffered framebuffer:
every frame is written to all pages because the menu may leave either one on screen.
"""
import mmap
import os
import select
import struct
from fcntl import ioctl

from PIL import Image, ImageDraw, ImageFont

W, H = 720, 480
FONT = "/usr/share/fonts/TTF/DejaVuSansMono.ttf"
FB_CFG = "/mnt/mod/ctrl/configs/fb.cfg"

BG = (18, 18, 24)
FG = (235, 235, 235)
DIM = (150, 150, 160)
ACCENT = (40, 110, 220)
BAR_BG = (55, 55, 65)
SEL = (45, 60, 95)
OK = (60, 170, 90)
WARN = (220, 160, 40)
BAD = (210, 60, 60)

# evdev codes on /dev/input/event1 (same mapping as the stock apps)
A, B, X, Y = 304, 305, 307, 306
L1, R1, SELECT, START, MENU = 308, 309, 310, 311, 312
DX, DY = 16, 17  # D-pad axes (ABS_HAT0X / ABS_HAT0Y), value -1 / +1

_fonts = {}


def font(size):
    if size not in _fonts:
        _fonts[size] = ImageFont.truetype(FONT, size)
    return _fonts[size]


def human(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024 or unit == "TB":
            return f"{n:.1f} {unit}" if unit in ("GB", "TB") else f"{n:.0f} {unit}"
        n /= 1024


def canvas(title):
    img = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(img)
    d.rectangle((0, 0, W, 52), fill=ACCENT)
    d.text((20, 26), title, font=font(26), fill=FG, anchor="lm")
    return img, d


def footer(d, text):
    d.text((20, H - 22), text, font=font(17), fill=DIM, anchor="lm")


def fit(text, size, width):
    """Cuts text with an ellipsis so it fits in `width` pixels."""
    f = font(size)
    if f.getlength(text) <= width:
        return text
    while text and f.getlength(text + "…") > width:
        text = text[:-1]
    return text + "…"


def wrap(text, size, width):
    lines, line = [], ""
    for word in text.split():
        test = f"{line} {word}".strip()
        if font(size).getlength(test) <= width:
            line = test
        else:
            if line:
                lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


class Screen:
    def __init__(self):
        self.fb = os.open("/dev/fb0", os.O_RDWR)
        if os.path.exists(FB_CFG):
            with open(FB_CFG, "rb") as f:
                ioctl(self.fb, 0x4601, bytearray(f.read()))
        ioctl(self.fb, 0x4611, 0)
        try:
            with open("/sys/class/graphics/fb0/virtual_size") as f:
                self.pages = max(1, int(f.read().split(",")[1]) // H)
        except (OSError, ValueError, IndexError):
            self.pages = 1
        self.mm = mmap.mmap(self.fb, W * H * 4 * self.pages)

    def show(self, img):
        data = img.convert("RGBA").tobytes("raw", "BGRA")
        self.mm.seek(0)
        for _ in range(self.pages):
            self.mm.write(data)

    def close(self):
        self.mm.close()
        os.close(self.fb)


class Input:
    """Button presses from /dev/input/event1; wait() can time out (for live screens)."""

    def __init__(self):
        self.fd = os.open("/dev/input/event1", os.O_RDONLY | os.O_NONBLOCK)
        self.size = struct.calcsize("llHHi")

    def wait(self, timeout=None):
        """Returns (code, value) of the next press/repeat, or None after `timeout` seconds."""
        while True:
            r, _, _ = select.select([self.fd], [], [], timeout)
            if not r:
                return None
            try:
                data = os.read(self.fd, self.size)
            except BlockingIOError:
                continue
            if len(data) < self.size:
                continue
            _, _, etype, code, value = struct.unpack("llHHi", data)
            if etype in (1, 3) and value != 0:
                return code, value

    def close(self):
        os.close(self.fd)
