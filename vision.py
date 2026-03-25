"""
Screenshot capture and image recognition for Roblox.

Captures the Roblox window from the hidden sandbox desktop using
PrintWindow (Win32 API) and finds GUI elements using OpenCV
template matching.
"""

import ctypes
import ctypes.wintypes as wintypes
from pathlib import Path
from queue import Empty

import cv2
import numpy as np

user32 = ctypes.windll.user32
gdi32 = ctypes.windll.gdi32

IMAGES_DIR = Path(__file__).parent / "images"
IMAGES_DIR.mkdir(exist_ok=True)

SCREENSHOTS_DIR = Path(__file__).parent / "screenshots"
SCREENSHOTS_DIR.mkdir(exist_ok=True)

# ── PrintWindow constants ─────────────────────────────────────────────────────
PW_CLIENTONLY = 0x00000001
PW_RENDERFULLCONTENT = 0x00000002

# ── GDI constants ─────────────────────────────────────────────────────────────
BI_RGB = 0
DIB_RGB_COLORS = 0


# ── Bitmap structures ─────────────────────────────────────────────────────────

class BITMAPINFOHEADER(ctypes.Structure):
    _fields_ = [
        ("biSize", wintypes.DWORD),
        ("biWidth", wintypes.LONG),
        ("biHeight", wintypes.LONG),
        ("biPlanes", wintypes.WORD),
        ("biBitCount", wintypes.WORD),
        ("biCompression", wintypes.DWORD),
        ("biSizeImage", wintypes.DWORD),
        ("biXPelsPerMeter", wintypes.LONG),
        ("biYPelsPerMeter", wintypes.LONG),
        ("biClrUsed", wintypes.DWORD),
        ("biClrImportant", wintypes.DWORD),
    ]


class BITMAPINFO(ctypes.Structure):
    _fields_ = [
        ("bmiHeader", BITMAPINFOHEADER),
        ("bmiColors", wintypes.DWORD * 3),
    ]


# ═══════════════════════════════════════════════════════════════════════════════
# Screenshot capture
# ═══════════════════════════════════════════════════════════════════════════════


def capture_window(hwnd: int) -> np.ndarray | None:
    """
    Capture a window's client area using PrintWindow.

    Must be called from a thread attached to the window's desktop
    (i.e., the sandbox worker thread).

    Returns a BGR numpy array (OpenCV-compatible) or None on failure.
    """
    # Get client area size
    rect = wintypes.RECT()
    user32.GetClientRect(hwnd, ctypes.byref(rect))
    width = rect.right - rect.left
    height = rect.bottom - rect.top
    if width <= 0 or height <= 0:
        return None

    # Create a device context and bitmap to draw into
    hdc_window = user32.GetDC(hwnd)
    if not hdc_window:
        return None

    hdc_mem = gdi32.CreateCompatibleDC(hdc_window)
    if not hdc_mem:
        user32.ReleaseDC(hwnd, hdc_window)
        return None

    hbitmap = gdi32.CreateCompatibleBitmap(hdc_window, width, height)
    if not hbitmap:
        gdi32.DeleteDC(hdc_mem)
        user32.ReleaseDC(hwnd, hdc_window)
        return None

    old_bmp = gdi32.SelectObject(hdc_mem, hbitmap)

    # Capture the window contents
    user32.PrintWindow(hwnd, hdc_mem, PW_CLIENTONLY | PW_RENDERFULLCONTENT)

    # Read the bitmap pixels into a buffer
    bmi = BITMAPINFO()
    bmi.bmiHeader.biSize = ctypes.sizeof(BITMAPINFOHEADER)
    bmi.bmiHeader.biWidth = width
    bmi.bmiHeader.biHeight = -height  # negative = top-down row order
    bmi.bmiHeader.biPlanes = 1
    bmi.bmiHeader.biBitCount = 32  # BGRA
    bmi.bmiHeader.biCompression = BI_RGB

    buf_size = width * height * 4
    buf = (ctypes.c_ubyte * buf_size)()
    gdi32.GetDIBits(
        hdc_mem, hbitmap, 0, height,
        buf, ctypes.byref(bmi), DIB_RGB_COLORS,
    )

    # Cleanup GDI objects
    gdi32.SelectObject(hdc_mem, old_bmp)
    gdi32.DeleteObject(hbitmap)
    gdi32.DeleteDC(hdc_mem)
    user32.ReleaseDC(hwnd, hdc_window)

    # Convert BGRA buffer to BGR numpy array
    img = np.frombuffer(buf, dtype=np.uint8).reshape(height, width, 4)
    return img[:, :, :3].copy()  # drop alpha, copy to own memory


def capture_screenshot(sandbox) -> np.ndarray | None:
    """
    Capture the Roblox window on the sandbox desktop.

    Queues a screenshot command to the sandbox worker thread and
    waits for the result.
    """
    if not sandbox or not sandbox.is_active():
        return None

    # Drain stale results (same pattern as sandbox.get_roblox_hwnd)
    while not sandbox._result_queue.empty():
        try:
            sandbox._result_queue.get_nowait()
        except Empty:
            break

    sandbox._queue.put({"action": "screenshot"})
    try:
        return sandbox._result_queue.get(timeout=10)
    except Empty:
        return None


def save_screenshot(sandbox, filename: str | None = None) -> str | None:
    """Capture and save a screenshot to the screenshots/ directory."""
    img = capture_screenshot(sandbox)
    if img is None:
        return None

    if filename is None:
        import time
        filename = f"roblox_{int(time.time())}.png"

    path = SCREENSHOTS_DIR / filename
    cv2.imwrite(str(path), img)
    return str(path)


# ═══════════════════════════════════════════════════════════════════════════════
# Template matching
# ═══════════════════════════════════════════════════════════════════════════════


class ImageMatcher:
    """Find template images within a screenshot using OpenCV."""

    DEFAULT_THRESHOLD = 0.8

    @staticmethod
    def load_template(name: str) -> np.ndarray | None:
        """
        Load a template image.

        If *name* is an absolute path (or existing relative path), load
        directly from that path.  Otherwise look in the images/ directory.
        Accepts filenames with or without .png extension.
        """
        # Try as a direct / absolute path first
        direct = Path(name)
        if direct.is_absolute() and direct.exists():
            return cv2.imread(str(direct), cv2.IMREAD_COLOR)

        # Fallback: look in images/ directory
        path = IMAGES_DIR / name
        if not path.exists():
            path = IMAGES_DIR / f"{name}.png"
        if not path.exists():
            return None
        return cv2.imread(str(path), cv2.IMREAD_COLOR)

    @staticmethod
    def find(
        screenshot: np.ndarray,
        template: np.ndarray,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> tuple[int, int, float] | None:
        """
        Find the best match of template in screenshot.

        Returns (center_x, center_y, confidence) or None if below threshold.
        Coordinates are relative to the window's client area.
        """
        if screenshot is None or template is None:
            return None

        # Template must be smaller than screenshot
        sh, sw = screenshot.shape[:2]
        th, tw = template.shape[:2]
        if th > sh or tw > sw:
            return None

        result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        _, max_val, _, max_loc = cv2.minMaxLoc(result)

        if max_val < threshold:
            return None

        cx = max_loc[0] + tw // 2
        cy = max_loc[1] + th // 2
        return (cx, cy, float(max_val))

    @staticmethod
    def find_all(
        screenshot: np.ndarray,
        template: np.ndarray,
        threshold: float = DEFAULT_THRESHOLD,
    ) -> list[tuple[int, int, float]]:
        """
        Find all matches above threshold.

        Returns list of (center_x, center_y, confidence).
        """
        if screenshot is None or template is None:
            return []

        sh, sw = screenshot.shape[:2]
        th, tw = template.shape[:2]
        if th > sh or tw > sw:
            return []

        result = cv2.matchTemplate(screenshot, template, cv2.TM_CCOEFF_NORMED)
        locations = np.where(result >= threshold)

        matches = []
        for pt in zip(*locations[::-1]):
            cx = pt[0] + tw // 2
            cy = pt[1] + th // 2
            matches.append((cx, cy, float(result[pt[1], pt[0]])))
        return matches


def list_images() -> list[str]:
    """List all template images in the images/ directory."""
    return sorted(p.name for p in IMAGES_DIR.glob("*.png"))
