"""
Macro recording, playback, and scheduling.

Record mouse clicks and keypresses while Roblox is focused,
then replay them.

Without sandbox: playback via PostMessage (GUI clicks only).
With sandbox:    playback via SendInput on hidden desktop (EVERYTHING works).
"""

import ctypes
import ctypes.wintypes
import json
import threading
import time
from dataclasses import dataclass, asdict
from pathlib import Path

from pynput import mouse as pynput_mouse
from pynput import keyboard as pynput_keyboard

from background_input import send_click, send_key
from utils import get_roblox_window_handle

user32 = ctypes.windll.user32

MACROS_DIR = Path(__file__).parent / "macros"
MACROS_DIR.mkdir(exist_ok=True)


# ── data model ────────────────────────────────────────────────────────────────

@dataclass
class MacroAction:
    type: str               # "click", "key_tap", "wait"
    x: int = 0              # window-relative coords for clicks
    y: int = 0
    button: str = "left"    # "left" / "right"
    vk: int = 0             # virtual-key code for key_tap
    delay_after: float = 0.0  # seconds to wait before next action


def _actions_to_dicts(actions: list[MacroAction]) -> list[dict]:
    return [asdict(a) for a in actions]


def _dicts_to_actions(dicts: list[dict]) -> list[MacroAction]:
    return [MacroAction(**d) for d in dicts]


# ── save / load ───────────────────────────────────────────────────────────────

def save_macro(name: str, actions: list[MacroAction]):
    path = MACROS_DIR / f"{name}.json"
    data = {"name": name, "actions": _actions_to_dicts(actions)}
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def load_macro(name: str) -> list[MacroAction] | None:
    path = MACROS_DIR / f"{name}.json"
    if not path.exists():
        return None
    data = json.loads(path.read_text(encoding="utf-8"))
    return _dicts_to_actions(data["actions"])


def list_macros() -> list[str]:
    return sorted(p.stem for p in MACROS_DIR.glob("*.json"))


def delete_macro(name: str) -> bool:
    path = MACROS_DIR / f"{name}.json"
    if path.exists():
        path.unlink()
        return True
    return False


# ── coordinate conversion ─────────────────────────────────────────────────────

def _screen_to_client(hwnd: int, sx: int, sy: int) -> tuple[int, int]:
    """Convert screen coordinates to window-client coordinates."""
    pt = ctypes.wintypes.POINT(sx, sy)
    user32.ScreenToClient(hwnd, ctypes.byref(pt))
    return pt.x, pt.y


# ── recorder ──────────────────────────────────────────────────────────────────

class MacroRecorder:
    """
    Records mouse clicks and keypresses while Roblox is focused.
    Press F6 to stop recording.
    """

    def __init__(self, hwnd: int):
        self._hwnd = hwnd
        self._actions: list[MacroAction] = []
        self._last_time: float = 0.0
        self._stop = False
        self._mouse_listener: pynput_mouse.Listener | None = None
        self._kb_listener: pynput_keyboard.Listener | None = None

    def _is_roblox_focused(self) -> bool:
        return user32.GetForegroundWindow() == self._hwnd

    def _delay(self) -> float:
        now = time.time()
        if self._last_time == 0:
            d = 0.0
        else:
            d = round(now - self._last_time, 3)
        self._last_time = now
        return d

    # ── pynput callbacks ──────────────────────────────────────────────

    def _on_click(self, x: int, y: int, button, pressed: bool):
        if self._stop:
            return False
        if not pressed:  # only record on press, not release
            return
        if not self._is_roblox_focused():
            return

        cx, cy = _screen_to_client(self._hwnd, x, y)
        btn = "right" if button == pynput_mouse.Button.right else "left"
        delay = self._delay()

        # set delay_after on the PREVIOUS action
        if self._actions:
            self._actions[-1].delay_after = delay

        self._actions.append(MacroAction(
            type="click", x=cx, y=cy, button=btn,
        ))

    def _on_key_press(self, key):
        if self._stop:
            return False

        # F6 stops recording
        if key == pynput_keyboard.Key.f6:
            self._stop = True
            return False

        if not self._is_roblox_focused():
            return

        # get the virtual-key code
        vk = 0
        if hasattr(key, "vk") and key.vk is not None:
            vk = key.vk
        elif hasattr(key, "value") and hasattr(key.value, "vk"):
            vk = key.value.vk
        if vk == 0:
            return

        delay = self._delay()
        if self._actions:
            self._actions[-1].delay_after = delay

        self._actions.append(MacroAction(type="key_tap", vk=vk))

    # ── public API ────────────────────────────────────────────────────

    def start(self):
        self._actions.clear()
        self._last_time = 0.0
        self._stop = False

        self._mouse_listener = pynput_mouse.Listener(on_click=self._on_click)
        self._kb_listener = pynput_keyboard.Listener(on_press=self._on_key_press)
        self._mouse_listener.start()
        self._kb_listener.start()

    def stop(self) -> list[MacroAction]:
        self._stop = True
        if self._mouse_listener:
            self._mouse_listener.stop()
        if self._kb_listener:
            self._kb_listener.stop()
        return self._actions

    def is_recording(self) -> bool:
        return not self._stop and self._mouse_listener is not None


# ── player ────────────────────────────────────────────────────────────────────

class MacroPlayer:
    """Replay a macro. Uses sandbox SendInput if available, else PostMessage."""

    @staticmethod
    def play(actions: list[MacroAction], hwnd: int | None = None, sandbox=None):
        for action in actions:
            if sandbox and sandbox.is_active():
                # Full input via SendInput on hidden desktop
                if action.type == "click":
                    sandbox.send_click(action.x, action.y, button=action.button)
                elif action.type == "key_tap":
                    sandbox.send_key(action.vk)
            elif hwnd:
                # PostMessage fallback (GUI clicks only)
                if action.type == "click":
                    send_click(hwnd, action.x, action.y, button=action.button)
                elif action.type == "key_tap":
                    send_key(hwnd, action.vk)

            if action.delay_after > 0:
                time.sleep(action.delay_after)


# ── scheduler ─────────────────────────────────────────────────────────────────

class MacroScheduler:
    """Run a macro on a repeating timer in a background thread."""

    def __init__(self):
        self._running = False
        self._thread: threading.Thread | None = None
        self.macro_name: str = ""
        self.interval: float = 0.0  # minutes
        self.sandbox = None  # set externally

    def _loop(self, hwnd_func, actions: list[MacroAction], interval_sec: float):
        while self._running:
            if self.sandbox and self.sandbox.is_active():
                MacroPlayer.play(actions, sandbox=self.sandbox)
            else:
                hwnd = hwnd_func()
                if hwnd is not None:
                    MacroPlayer.play(actions, hwnd=hwnd)

            # interruptible sleep
            for _ in range(int(interval_sec)):
                if not self._running:
                    return
                time.sleep(1)

    def start(self, macro_name: str, actions: list[MacroAction], interval_minutes: float):
        if self._running:
            return
        self.macro_name = macro_name
        self.interval = interval_minutes
        self._running = True
        self._thread = threading.Thread(
            target=self._loop,
            args=(get_roblox_window_handle, actions, interval_minutes * 60),
            daemon=True,
        )
        self._thread.start()

    def stop(self):
        self._running = False
        if self._thread:
            self._thread.join(timeout=5)
            self._thread = None
        self.macro_name = ""

    def is_running(self) -> bool:
        return self._running
