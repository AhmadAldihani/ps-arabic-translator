"""Grab the picture of the PS Remote Play window (Windows only)."""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes

from PIL import Image

IS_WINDOWS = sys.platform == "win32"

if IS_WINDOWS:
    user32 = ctypes.windll.user32
    gdi32 = ctypes.windll.gdi32
    # 64-bit handles: declare types so ctypes never truncates them to 32 bits.
    H, HW = wintypes.HANDLE, wintypes.HWND
    user32.GetDC.argtypes, user32.GetDC.restype = [HW], H
    user32.ReleaseDC.argtypes = [HW, H]
    user32.PrintWindow.argtypes, user32.PrintWindow.restype = [HW, H, wintypes.UINT], wintypes.BOOL
    user32.GetClientRect.argtypes = [HW, ctypes.POINTER(wintypes.RECT)]
    user32.ClientToScreen.argtypes = [HW, ctypes.POINTER(wintypes.POINT)]
    user32.IsWindow.argtypes = user32.IsIconic.argtypes = user32.IsWindowVisible.argtypes = [HW]
    user32.GetWindowTextLengthW.argtypes = [HW]
    user32.GetWindowTextW.argtypes = [HW, wintypes.LPWSTR, ctypes.c_int]
    gdi32.CreateCompatibleDC.argtypes, gdi32.CreateCompatibleDC.restype = [H], H
    gdi32.CreateCompatibleBitmap.argtypes, gdi32.CreateCompatibleBitmap.restype = [H, ctypes.c_int, ctypes.c_int], H
    gdi32.SelectObject.argtypes, gdi32.SelectObject.restype = [H, H], H
    gdi32.DeleteObject.argtypes = [H]
    gdi32.DeleteDC.argtypes = [H]
    gdi32.GetDIBits.argtypes = [H, H, wintypes.UINT, wintypes.UINT, ctypes.c_void_p, ctypes.c_void_p, wintypes.UINT]
    try:  # sharp, unscaled pixels on high-DPI laptops
        ctypes.windll.shcore.SetProcessDpiAwareness(2)
    except Exception:  # noqa: BLE001
        try:
            user32.SetProcessDPIAware()
        except Exception:  # noqa: BLE001
            pass

PW_CLIENTONLY = 0x1
PW_RENDERFULLCONTENT = 0x2
SOURCE_HINTS = ("PS Remote Play", "PS Remote", "Remote Play", "chiaki", "Chiaki")


class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD), ("biWidth", wintypes.LONG), ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD), ("biBitCount", wintypes.WORD), ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD), ("biXPelsPerMeter", wintypes.LONG), ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD), ("biClrImportant", wintypes.DWORD),
    ]


def list_windows() -> list[dict]:
    """Visible top-level windows with a title: [{hwnd, title, minimized, likely}]."""
    if not IS_WINDOWS:
        return []
    out: list[dict] = []
    proto = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        n = user32.GetWindowTextLengthW(hwnd)
        if n <= 0:
            return True
        buf = ctypes.create_unicode_buffer(n + 1)
        user32.GetWindowTextW(hwnd, buf, n + 1)
        title = buf.value.strip()
        if not title or title in ("Program Manager", "Settings"):
            return True
        rect = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        if rect.right - rect.left < 200 or rect.bottom - rect.top < 120:
            return True
        out.append({
            "hwnd": int(hwnd or 0),
            "title": title,
            "minimized": bool(user32.IsIconic(hwnd)),
            "likely": any(h.lower() in title.lower() for h in SOURCE_HINTS),
        })
        return True

    user32.EnumWindows(proto(cb), 0)
    out.sort(key=lambda w: (not w["likely"], w["title"].lower()))
    return out


def find_window(title: str | None) -> int | None:
    wins = list_windows()
    if title:
        for w in wins:
            if w["title"] == title:
                return w["hwnd"]
        for w in wins:
            if title.lower() in w["title"].lower():
                return w["hwnd"]
    for w in wins:
        if w["likely"]:
            return w["hwnd"]
    return None


def is_minimized(hwnd: int) -> bool:
    return IS_WINDOWS and bool(user32.IsIconic(hwnd))


def capture_window(hwnd: int) -> Image.Image | None:
    """Client area of the window, even when other windows cover it (not when minimized)."""
    if not IS_WINDOWS or not user32.IsWindow(hwnd) or user32.IsIconic(hwnd):
        return None
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    w, h = rect.right - rect.left, rect.bottom - rect.top
    if w <= 0 or h <= 0:
        return None
    img = _print_window(hwnd, w, h)
    if img is None or _looks_black(img):
        img = _screen_grab(hwnd, w, h) or img
    return img


def _print_window(hwnd: int, w: int, h: int) -> Image.Image | None:
    hdc_win = user32.GetDC(hwnd)
    hdc = gdi32.CreateCompatibleDC(hdc_win)
    bmp = gdi32.CreateCompatibleBitmap(hdc_win, w, h)
    old = gdi32.SelectObject(hdc, bmp)
    try:
        ok = user32.PrintWindow(hwnd, hdc, PW_CLIENTONLY | PW_RENDERFULLCONTENT)
        if not ok:
            return None
        bi = BITMAPINFOHEADER()
        bi.biSize = ctypes.sizeof(BITMAPINFOHEADER)
        bi.biWidth, bi.biHeight = w, -h  # negative: top-down rows
        bi.biPlanes, bi.biBitCount, bi.biCompression = 1, 32, 0
        buf = ctypes.create_string_buffer(w * h * 4)
        got = gdi32.GetDIBits(hdc, bmp, 0, h, buf, ctypes.byref(bi), 0)
        if got != h:
            return None
        return Image.frombuffer("RGB", (w, h), buf.raw, "raw", "BGRX", 0, 1)
    finally:
        gdi32.SelectObject(hdc, old)
        gdi32.DeleteObject(bmp)
        gdi32.DeleteDC(hdc)
        user32.ReleaseDC(hwnd, hdc_win)


def _screen_grab(hwnd: int, w: int, h: int) -> Image.Image | None:
    """Fallback for windows that PrintWindow returns black for: copy what is on screen."""
    try:
        import mss
    except ImportError:
        return None
    pt = wintypes.POINT(0, 0)
    user32.ClientToScreen(hwnd, ctypes.byref(pt))
    with mss.mss() as sct:
        shot = sct.grab({"left": pt.x, "top": pt.y, "width": w, "height": h})
        return Image.frombytes("RGB", shot.size, shot.bgra, "raw", "BGRX")


def _looks_black(img: Image.Image) -> bool:
    small = img.convert("L").resize((64, 36))
    return max(small.getdata()) < 6


def game_rect(width: int, height: int, aspect: float = 16 / 9) -> tuple[int, int, int, int]:
    """Where the 16:9 game picture sits inside a window of this size (letterbox/pillarbox)."""
    if width / height > aspect:
        gw = round(height * aspect)
        return ((width - gw) // 2, 0, gw, height)
    gh = round(width / aspect)
    return (0, (height - gh) // 2, width, gh)


def content_rect(img: Image.Image) -> tuple[int, int, int, int] | None:
    """Bounding box of everything that is not black bars (x, y, w, h), or None if all dark."""
    small = img.convert("L").resize((192, 108))
    mask = small.point(lambda v: 255 if v > 22 else 0)
    bbox = mask.getbbox()
    if not bbox:
        return None
    sx, sy = img.width / 192, img.height / 108
    x0, y0, x1, y1 = bbox
    return (round(x0 * sx), round(y0 * sy), round((x1 - x0) * sx), round((y1 - y0) * sy))


class VideoArea:
    """Learns where the game picture is inside the Remote Play window.

    Dark scenes hide the picture's edges, so the bright area is merged over many frames; it is
    trusted once it looks like a 16:9 picture, otherwise the window is assumed to letterbox 16:9.
    """

    def __init__(self):
        self.size = None
        self.union = None

    def update(self, img: Image.Image) -> tuple[int, int, int, int]:
        if img.size != self.size:
            self.size, self.union = img.size, None
        r = content_rect(img)
        if r:
            if self.union is None:
                self.union = r
            else:
                x0 = min(self.union[0], r[0]); y0 = min(self.union[1], r[1])
                x1 = max(self.union[0] + self.union[2], r[0] + r[2]); y1 = max(self.union[1] + self.union[3], r[1] + r[3])
                self.union = (x0, y0, x1 - x0, y1 - y0)
        return self.rect()

    def rect(self) -> tuple[int, int, int, int]:
        w, h = self.size
        fallback = game_rect(w, h)
        u = self.union
        if not u or u[3] == 0:
            return fallback
        aspect = u[2] / u[3]
        big = u[2] * u[3] >= 0.45 * fallback[2] * fallback[3]
        if big and 1.70 <= aspect <= 1.86:
            return u
        return fallback
