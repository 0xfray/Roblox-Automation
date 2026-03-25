"""
Send keyboard and mouse input to a window WITHOUT stealing focus.

Uses PostMessage so the target window receives events in the
background while you keep using other apps.

Works for Roblox:
  ✓  Clicking GUI buttons / menus at coordinates
  ✓  Typing text (chat via WM_CHAR)
  ✓  Anti-AFK mouse activity
  ✗  WASD character movement  (Roblox requires window focus)
  ✗  Camera rotation          (Roblox uses raw mouse input)
  ✗  Jumping / space bar      (game-engine input, needs focus)
"""

import platform
import time

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    import ctypes
    import ctypes.wintypes
    user32 = ctypes.windll.user32
else:
    ctypes = None  # type: ignore
    user32 = None

# ── Windows messages ──────────────────────────────────────────────────────────
WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_CHAR = 0x0102
WM_MOUSEMOVE = 0x0200
WM_LBUTTONDOWN = 0x0201
WM_LBUTTONUP = 0x0202
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
MK_LBUTTON = 0x0001
MK_RBUTTON = 0x0002


def _make_lparam(x: int, y: int) -> int:
    """Pack (x, y) into an LPARAM for mouse messages."""
    return (y << 16) | (x & 0xFFFF)


def _make_key_lparam(scan: int, repeat: int = 1, up: bool = False) -> int:
    """Build lParam for WM_KEYDOWN / WM_KEYUP."""
    lp = repeat & 0xFFFF
    lp |= (scan & 0xFF) << 16
    if up:
        lp |= (1 << 30) | (1 << 31)
    return lp


# ── public API ────────────────────────────────────────────────────────────────

def send_key(hwnd: int, vk_code: int, hold: float = 0.05):
    if not IS_WINDOWS:
        return
    """
    Press and release a key in the background window.

    Parameters
    ----------
    hwnd     : window handle
    vk_code  : virtual-key code (e.g. 0x57 for W)
    hold     : seconds to hold the key down
    """
    scan = user32.MapVirtualKeyW(vk_code, 0)
    lp_down = _make_key_lparam(scan)
    lp_up = _make_key_lparam(scan, up=True)
    user32.PostMessageW(hwnd, WM_KEYDOWN, vk_code, lp_down)
    time.sleep(hold)
    user32.PostMessageW(hwnd, WM_KEYUP, vk_code, lp_up)


def hold_key(hwnd: int, vk_code: int, duration: float):
    if not IS_WINDOWS:
        return
    """
    Hold a key down for *duration* seconds, then release.
    Sends repeated WM_KEYDOWN every 50 ms to keep the key held.
    """
    scan = user32.MapVirtualKeyW(vk_code, 0)
    lp_down = _make_key_lparam(scan)
    lp_up = _make_key_lparam(scan, up=True)

    end = time.time() + duration
    while time.time() < end:
        user32.PostMessageW(hwnd, WM_KEYDOWN, vk_code, lp_down)
        time.sleep(0.05)
    user32.PostMessageW(hwnd, WM_KEYUP, vk_code, lp_up)


def send_click(hwnd: int, x: int, y: int, button: str = "left"):
    if not IS_WINDOWS:
        return
    """
    Click at (x, y) inside the window without stealing focus.

    Coordinates are relative to the window's client area (top-left = 0,0).

    Parameters
    ----------
    hwnd   : window handle
    x, y   : click position relative to the window client area
    button : "left" or "right"
    """
    lp = _make_lparam(x, y)
    if button == "right":
        user32.PostMessageW(hwnd, WM_RBUTTONDOWN, MK_RBUTTON, lp)
        time.sleep(0.05)
        user32.PostMessageW(hwnd, WM_RBUTTONUP, 0, lp)
    else:
        user32.PostMessageW(hwnd, WM_LBUTTONDOWN, MK_LBUTTON, lp)
        time.sleep(0.05)
        user32.PostMessageW(hwnd, WM_LBUTTONUP, 0, lp)


def send_mouse_move(hwnd: int, x: int, y: int):
    if not IS_WINDOWS:
        return
    """Move the mouse cursor inside the window (background)."""
    lp = _make_lparam(x, y)
    user32.PostMessageW(hwnd, WM_MOUSEMOVE, 0, lp)


def send_text(hwnd: int, text: str, delay: float = 0.03):
    if not IS_WINDOWS:
        return
    """
    Type a string of text into the background window via WM_CHAR.
    Good for chat messages or text input fields.
    """
    for ch in text:
        user32.PostMessageW(hwnd, WM_CHAR, ord(ch), 0)
        time.sleep(delay)


def get_window_size(hwnd: int) -> tuple[int, int]:
    if not IS_WINDOWS:
        return (800, 600)
    """Return (width, height) of the window's client area."""
    rect = ctypes.wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    return rect.right - rect.left, rect.bottom - rect.top
