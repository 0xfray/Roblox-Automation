import ctypes
import ctypes.wintypes
import threading
import time
import random

from rich.console import Console

from constants import (
    WM_KEYDOWN,
    WM_KEYUP,
    INPUT_KEYBOARD,
    KEYEVENTF_KEYUP,
    AFK_KEYS,
    DEFAULT_AFK_INTERVAL,
)
from utils import get_roblox_window_handle


# ── ctypes structures for SendInput ───────────────────────────────────────────

class KEYBDINPUT(ctypes.Structure):
    _fields_ = [
        ("wVk", ctypes.c_ushort),
        ("wScan", ctypes.c_ushort),
        ("dwFlags", ctypes.c_ulong),
        ("time", ctypes.c_ulong),
        ("dwExtraInfo", ctypes.POINTER(ctypes.c_ulong)),
    ]


class INPUT_UNION(ctypes.Union):
    _fields_ = [("ki", KEYBDINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [
        ("type", ctypes.c_ulong),
        ("ii", INPUT_UNION),
    ]


user32 = ctypes.windll.user32


def _make_key_input(vk: int, flags: int = 0) -> INPUT:
    scan = user32.MapVirtualKeyW(vk, 0)
    ki = KEYBDINPUT(
        wVk=vk,
        wScan=scan,
        dwFlags=flags,
        time=0,
        dwExtraInfo=ctypes.pointer(ctypes.c_ulong(0)),
    )
    inp = INPUT(type=INPUT_KEYBOARD)
    inp.ii.ki = ki
    return inp


def _send_input(*inputs: INPUT):
    arr = (INPUT * len(inputs))(*inputs)
    ctypes.windll.user32.SendInput(len(arr), arr, ctypes.sizeof(INPUT))


# ── AntiAFK class ─────────────────────────────────────────────────────────────

class AntiAFK:
    """
    Prevents Roblox AFK kick by periodically sending keypresses.

    Strategies
    ----------
    foreground : Brings Roblox to front, sends via SendInput (reliable).
    sendmessage : Posts WM_KEYDOWN/UP to the window handle (may not work
                  with DirectInput when Roblox is unfocused).
    """

    def __init__(self, console: Console, interval: int = DEFAULT_AFK_INTERVAL):
        self.console = console
        self.interval = interval
        self.strategy = "foreground"
        self._running = False
        self._thread: threading.Thread | None = None

    # ── key sending strategies ────────────────────────────────────────────

    def _send_foreground(self, hwnd: int, vk: int):
        prev = user32.GetForegroundWindow()
        user32.SetForegroundWindow(hwnd)
        time.sleep(0.05)

        down = _make_key_input(vk)
        up = _make_key_input(vk, KEYEVENTF_KEYUP)
        _send_input(down)
        time.sleep(0.05)
        _send_input(up)
        time.sleep(0.05)

        if prev:
            user32.SetForegroundWindow(prev)

    def _send_message(self, hwnd: int, vk: int):
        scan = user32.MapVirtualKeyW(vk, 0)
        lparam_down = (scan << 16) | 1
        lparam_up = (scan << 16) | 1 | (1 << 30) | (1 << 31)
        user32.PostMessageW(hwnd, WM_KEYDOWN, vk, lparam_down)
        time.sleep(0.05)
        user32.PostMessageW(hwnd, WM_KEYUP, vk, lparam_up)

    # ── background loop ──────────────────────────────────────────────────

    def _loop(self):
        while self._running:
            # interruptible sleep
            for _ in range(self.interval):
                if not self._running:
                    return
                time.sleep(1)

            hwnd = get_roblox_window_handle()
            if hwnd is None:
                continue

            vk = random.choice(AFK_KEYS)
            try:
                if self.strategy == "foreground":
                    self._send_foreground(hwnd, vk)
                else:
                    self._send_message(hwnd, vk)
            except Exception:
                pass  # best effort

    # ── public API ────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.console.print(
            f"[green]Anti-AFK started (every {self.interval}s, "
            f"strategy: {self.strategy}).[/]"
        )

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self.console.print("[yellow]Anti-AFK stopped.[/]")

    def is_running(self) -> bool:
        return self._running

    def set_interval(self, seconds: int):
        self.interval = seconds

    def set_strategy(self, strategy: str):
        if strategy in ("foreground", "sendmessage"):
            self.strategy = strategy
