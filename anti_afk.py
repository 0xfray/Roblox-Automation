import threading
import time
import random

from rich.console import Console

from constants import AFK_KEYS, DEFAULT_AFK_INTERVAL
from utils import get_roblox_window_handle
from background_input import send_key, send_click, get_window_size


class AntiAFK:
    """
    Prevents Roblox AFK kick by periodically sending keypresses.

    In sandbox mode: uses SendInput on the hidden desktop (full input).
    Without sandbox: uses PostMessage (background, limited to GUI clicks).
    """

    def __init__(self, console: Console, interval: int = DEFAULT_AFK_INTERVAL):
        self.console = console
        self.interval = interval
        self.sandbox = None  # set externally when sandbox is active
        self.restaurant_bot = None  # set externally; skip AFK when restaurant bot is active
        self._running = False
        self._thread: threading.Thread | None = None

    # ── background loop ──────────────────────────────────────────────────

    def _loop(self):
        while self._running:
            # interruptible sleep
            for _ in range(self.interval):
                if not self._running:
                    return
                time.sleep(1)

            # Skip AFK tick when restaurant bot is actively moving
            if (self.restaurant_bot is not None
                    and hasattr(self.restaurant_bot, 'is_running')
                    and self.restaurant_bot.is_running()):
                continue

            vk = random.choice(AFK_KEYS)

            # Sandbox mode: full SendInput on hidden desktop
            if self.sandbox and self.sandbox.is_active():
                try:
                    self.sandbox.send_key(vk)
                    size = self.sandbox.get_window_size()
                    if size:
                        w, h = size
                        cx, cy = w // 2, h // 2
                        jitter = random.randint(-20, 20)
                        self.sandbox.send_click(cx + jitter, cy + jitter)
                except Exception:
                    pass
                continue

            # Normal mode: PostMessage (background, limited)
            hwnd = get_roblox_window_handle()
            if hwnd is None:
                continue

            try:
                send_key(hwnd, vk, hold=0.05)
                try:
                    w, h = get_window_size(hwnd)
                    cx, cy = w // 2, h // 2
                    jitter = random.randint(-20, 20)
                    send_click(hwnd, cx + jitter, cy + jitter)
                except Exception:
                    pass
            except Exception:
                pass

    # ── public API ────────────────────────────────────────────────────────

    def start(self):
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(target=self._loop, daemon=True)
        self._thread.start()
        self.console.print(
            f"[green]Anti-AFK started (every {self.interval}s, background mode).[/]"
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
