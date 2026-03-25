"""
Windows Desktop Sandbox for Roblox.

Creates a hidden Windows desktop and runs Roblox on it. All input
(keyboard + mouse) goes through SendInput on the hidden desktop, so
WASD movement, jumping, clicking — everything works fully without
touching the user's main desktop.

This is NOT a VM. It shares the same OS, GPU, RAM, and CPU.
The only thing isolated is the input queue and window focus.
"""

import os
import platform
import threading
import time
from queue import Queue, Empty

# ── Platform gate: entire module is Windows-only ──────────────────────────────
# On non-Windows, export a lightweight stub and skip all ctypes/Win32 code.

if platform.system() != "Windows":
    class DesktopSandbox:
        """Stub for non-Windows platforms. Sandbox requires Windows desktop APIs."""
        def start(self): raise RuntimeError("Sandbox is only available on Windows")
        def stop(self): pass
        def is_active(self): return False
        def launch(self, uri): return False
        def send_key(self, vk): pass
        def send_click(self, x, y, button="left"): pass
        def get_window_size(self): return None
        def peek(self, seconds): pass
        def find_hwnd(self): return None
    # Nothing else in this module is needed on Linux.

else:
    # ── Windows imports ──
    import ctypes
    import ctypes.wintypes as wintypes
    import winreg
    user32 = ctypes.windll.user32
    kernel32 = ctypes.windll.kernel32
    shell32 = ctypes.windll.shell32

    # ── Desktop constants ─────────────────────────────────────────────────
    GENERIC_ALL = 0x10000000
    DESKTOP_ALL_ACCESS = 0x01FF | 0x000F0000 | 0x00100000
    INPUT_MOUSE = 0
    INPUT_KEYBOARD = 1
    MOUSEEVENTF_MOVE = 0x0001
    MOUSEEVENTF_LEFTDOWN = 0x0002
    MOUSEEVENTF_LEFTUP = 0x0004
    MOUSEEVENTF_RIGHTDOWN = 0x0008
    MOUSEEVENTF_RIGHTUP = 0x0010
    MOUSEEVENTF_ABSOLUTE = 0x8000
    KEYEVENTF_KEYUP = 0x0002
    SM_CXSCREEN = 0
    SM_CYSCREEN = 1
    SW_MAXIMIZE = 3

    PUL = ctypes.POINTER(ctypes.c_ulong)

    class MOUSEINPUT(ctypes.Structure):
        _fields_ = [("dx", ctypes.c_long), ("dy", ctypes.c_long), ("mouseData", ctypes.c_ulong),
                     ("dwFlags", ctypes.c_ulong), ("time", ctypes.c_ulong), ("dwExtraInfo", PUL)]

    class KEYBDINPUT(ctypes.Structure):
        _fields_ = [("wVk", ctypes.c_ushort), ("wScan", ctypes.c_ushort), ("dwFlags", ctypes.c_ulong),
                     ("time", ctypes.c_ulong), ("dwExtraInfo", PUL)]

    class HARDWAREINPUT(ctypes.Structure):
        _fields_ = [("uMsg", ctypes.c_ulong), ("wParamL", ctypes.c_ushort), ("wParamH", ctypes.c_ushort)]

    class _INPUTunion(ctypes.Union):
        _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]

    class INPUT(ctypes.Structure):
        _fields_ = [("type", ctypes.c_ulong), ("union", _INPUTunion)]

    class STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD), ("lpReserved", wintypes.LPWSTR), ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR), ("dwX", wintypes.DWORD), ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD), ("dwYSize", wintypes.DWORD), ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD), ("dwFillAttribute", wintypes.DWORD), ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD), ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.POINTER(ctypes.c_byte)), ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE), ("hStdError", wintypes.HANDLE),
        ]

    class PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [("hProcess", wintypes.HANDLE), ("hThread", wintypes.HANDLE),
                     ("dwProcessId", wintypes.DWORD), ("dwThreadId", wintypes.DWORD)]

    user32.SendInput.argtypes = [ctypes.c_uint, ctypes.POINTER(INPUT), ctypes.c_int]
    user32.SendInput.restype = ctypes.c_uint
    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    # The actual DesktopSandbox class follows at module level (overrides the stub)

class DesktopSandbox:
    """
    Runs Roblox on a hidden Windows desktop.

    Input is sent via SendInput from a dedicated thread attached to
    the hidden desktop. Since it's a separate desktop, SendInput
    affects only Roblox — your main desktop is completely untouched.

    Works for EVERYTHING: WASD, jumping, mouse clicks, camera, etc.
    """

    DESKTOP_NAME = "RobloxHeadless"

    def __init__(self):
        self._hdesktop = None
        self._input_thread: threading.Thread | None = None
        self._queue: Queue = Queue()
        self._running = False
        self._roblox_hwnd: int | None = None
        self._result_queue: Queue = Queue()

    # ── lifecycle ─────────────────────────────────────────────────────────

    def start(self):
        """Create the hidden desktop and start the input worker thread."""
        if self._running:
            return

        self._hdesktop = user32.CreateDesktopW(
            self.DESKTOP_NAME, None, None, 0, GENERIC_ALL, None
        )
        if not self._hdesktop:
            raise RuntimeError(
                f"CreateDesktopW failed (error {ctypes.GetLastError()}). "
                "Try running as administrator."
            )

        self._running = True
        self._input_thread = threading.Thread(
            target=self._worker, daemon=True, name="sandbox-input"
        )
        self._input_thread.start()

    def stop(self):
        """Shut down the sandbox desktop."""
        self._running = False
        self._queue.put(None)
        if self._input_thread:
            self._input_thread.join(timeout=5)
            self._input_thread = None
        if self._hdesktop:
            user32.CloseDesktop(self._hdesktop)
            self._hdesktop = None
        self._roblox_hwnd = None

    def is_active(self) -> bool:
        return self._running and self._hdesktop is not None

    # ── worker thread (attached to sandbox desktop) ───────────────────────

    def _worker(self):
        if not user32.SetThreadDesktop(self._hdesktop):
            print(f"[sandbox] SetThreadDesktop failed (error {ctypes.GetLastError()})")
            return

        while self._running:
            try:
                cmd = self._queue.get(timeout=0.5)
            except Empty:
                continue

            if cmd is None:
                break

            try:
                action = cmd["action"]
                if action == "send_key":
                    self._do_send_key(cmd["vk"], cmd.get("duration", 0.05))
                elif action == "hold_key":
                    self._do_hold_key(cmd["vk"], cmd["duration"])
                elif action == "hold_keys":
                    self._do_hold_keys(cmd["keys"], cmd["duration"])
                elif action == "send_click":
                    self._do_send_click(
                        cmd["x"], cmd["y"], cmd.get("button", "left")
                    )
                elif action == "find_hwnd":
                    hwnd = self._do_find_hwnd()
                    self._result_queue.put(hwnd)
                elif action == "peek":
                    self._do_peek(cmd.get("seconds", 15))
                elif action == "screenshot":
                    img = self._do_screenshot()
                    self._result_queue.put(img)
            except Exception as e:
                print(f"[sandbox] Error in {cmd.get('action', '?')}: {e}")

    # ── worker: input actions ─────────────────────────────────────────────

    def _do_send_key(self, vk: int, duration: float = 0.05):
        """SendInput key press on the sandbox desktop."""
        scan = user32.MapVirtualKeyW(vk, 0)
        extra = ctypes.pointer(ctypes.c_ulong(0))

        # key down
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = vk
        inp.union.ki.wScan = scan
        inp.union.ki.dwFlags = 0
        inp.union.ki.time = 0
        inp.union.ki.dwExtraInfo = extra
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

        time.sleep(duration)

        # key up
        inp2 = INPUT()
        inp2.type = INPUT_KEYBOARD
        inp2.union.ki.wVk = vk
        inp2.union.ki.wScan = scan
        inp2.union.ki.dwFlags = KEYEVENTF_KEYUP
        inp2.union.ki.time = 0
        inp2.union.ki.dwExtraInfo = extra
        user32.SendInput(1, ctypes.byref(inp2), ctypes.sizeof(INPUT))

    def _do_hold_key(self, vk: int, duration: float):
        """SendInput sustained key hold on the sandbox desktop."""
        scan = user32.MapVirtualKeyW(vk, 0)
        extra = ctypes.pointer(ctypes.c_ulong(0))

        # key down
        inp = INPUT()
        inp.type = INPUT_KEYBOARD
        inp.union.ki.wVk = vk
        inp.union.ki.wScan = scan
        inp.union.ki.dwFlags = 0
        inp.union.ki.time = 0
        inp.union.ki.dwExtraInfo = extra
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

        time.sleep(duration)

        # key up
        inp2 = INPUT()
        inp2.type = INPUT_KEYBOARD
        inp2.union.ki.wVk = vk
        inp2.union.ki.wScan = scan
        inp2.union.ki.dwFlags = KEYEVENTF_KEYUP
        inp2.union.ki.time = 0
        inp2.union.ki.dwExtraInfo = extra
        user32.SendInput(1, ctypes.byref(inp2), ctypes.sizeof(INPUT))

    def _do_hold_keys(self, vk_list: list[int], duration: float):
        """Hold multiple keys simultaneously for the given duration."""
        extra = ctypes.pointer(ctypes.c_ulong(0))

        # Press all keys down
        for vk in vk_list:
            scan = user32.MapVirtualKeyW(vk, 0)
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp.union.ki.wVk = vk
            inp.union.ki.wScan = scan
            inp.union.ki.dwFlags = 0
            inp.union.ki.time = 0
            inp.union.ki.dwExtraInfo = extra
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

        time.sleep(duration)

        # Release all keys
        for vk in vk_list:
            scan = user32.MapVirtualKeyW(vk, 0)
            inp = INPUT()
            inp.type = INPUT_KEYBOARD
            inp.union.ki.wVk = vk
            inp.union.ki.wScan = scan
            inp.union.ki.dwFlags = KEYEVENTF_KEYUP
            inp.union.ki.time = 0
            inp.union.ki.dwExtraInfo = extra
            user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))

    def _do_send_click(self, x: int, y: int, button: str = "left"):
        """SendInput mouse click on the sandbox desktop."""
        hwnd = self._roblox_hwnd or self._do_find_hwnd()
        if not hwnd:
            return

        abs_x, abs_y = self._client_to_absolute(hwnd, x, y)
        extra = ctypes.pointer(ctypes.c_ulong(0))

        # move mouse
        inp = INPUT()
        inp.type = INPUT_MOUSE
        inp.union.mi.dx = abs_x
        inp.union.mi.dy = abs_y
        inp.union.mi.mouseData = 0
        inp.union.mi.dwFlags = MOUSEEVENTF_MOVE | MOUSEEVENTF_ABSOLUTE
        inp.union.mi.time = 0
        inp.union.mi.dwExtraInfo = extra
        user32.SendInput(1, ctypes.byref(inp), ctypes.sizeof(INPUT))
        time.sleep(0.02)

        if button == "right":
            down_flag = MOUSEEVENTF_RIGHTDOWN
            up_flag = MOUSEEVENTF_RIGHTUP
        else:
            down_flag = MOUSEEVENTF_LEFTDOWN
            up_flag = MOUSEEVENTF_LEFTUP

        # mouse down
        inp2 = INPUT()
        inp2.type = INPUT_MOUSE
        inp2.union.mi.dx = abs_x
        inp2.union.mi.dy = abs_y
        inp2.union.mi.mouseData = 0
        inp2.union.mi.dwFlags = down_flag | MOUSEEVENTF_ABSOLUTE
        inp2.union.mi.time = 0
        inp2.union.mi.dwExtraInfo = extra
        user32.SendInput(1, ctypes.byref(inp2), ctypes.sizeof(INPUT))

        time.sleep(0.05)

        # mouse up
        inp3 = INPUT()
        inp3.type = INPUT_MOUSE
        inp3.union.mi.dx = abs_x
        inp3.union.mi.dy = abs_y
        inp3.union.mi.mouseData = 0
        inp3.union.mi.dwFlags = up_flag | MOUSEEVENTF_ABSOLUTE
        inp3.union.mi.time = 0
        inp3.union.mi.dwExtraInfo = extra
        user32.SendInput(1, ctypes.byref(inp3), ctypes.sizeof(INPUT))

    def _do_find_hwnd(self) -> int | None:
        """Find Roblox window on the sandbox desktop."""
        found = []

        @WNDENUMPROC
        def callback(hwnd, _lparam):
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, buf, length + 1)
                if "roblox" in buf.value.lower():
                    if user32.IsWindowVisible(hwnd):
                        found.append(hwnd)
            return True

        user32.EnumDesktopWindows(self._hdesktop, callback, 0)

        if found:
            self._roblox_hwnd = found[0]
            return found[0]
        return None

    def _do_peek(self, seconds: float):
        """Switch display to sandbox desktop, then switch back."""
        user32.SwitchDesktop(self._hdesktop)
        time.sleep(seconds)
        hdefault = user32.OpenDesktopW("Default", 0, False, GENERIC_ALL)
        if hdefault:
            user32.SwitchDesktop(hdefault)
            user32.CloseDesktop(hdefault)

    def _do_screenshot(self):
        """Capture Roblox window via PrintWindow. Called from worker thread."""
        hwnd = self._roblox_hwnd or self._do_find_hwnd()
        if not hwnd:
            return None
        # Deferred import to avoid circular dependency
        from vision import capture_window
        return capture_window(hwnd)

    # ── helpers ───────────────────────────────────────────────────────────

    def _client_to_absolute(self, hwnd: int, x: int, y: int) -> tuple[int, int]:
        """Convert window-client coords to SendInput absolute coords [0, 65535]."""
        pt = wintypes.POINT(x, y)
        user32.ClientToScreen(hwnd, ctypes.byref(pt))

        screen_w = user32.GetSystemMetrics(SM_CXSCREEN)
        screen_h = user32.GetSystemMetrics(SM_CYSCREEN)

        abs_x = int(pt.x * 65535 / max(screen_w - 1, 1))
        abs_y = int(pt.y * 65535 / max(screen_h - 1, 1))
        return abs_x, abs_y

    @staticmethod
    def _get_protocol_handler() -> str | None:
        """Look up the roblox-player: protocol handler executable."""
        try:
            key = winreg.OpenKey(
                winreg.HKEY_CLASSES_ROOT,
                r"roblox-player\shell\open\command",
            )
            value, _ = winreg.QueryValueEx(key, "")
            winreg.CloseKey(key)

            # value format: "C:\...\RobloxPlayerLauncher.exe" %1
            if value.startswith('"'):
                exe = value.split('"')[1]
            else:
                exe = value.split()[0]

            return exe if exe and os.path.exists(exe) else None
        except (OSError, IndexError, ValueError):
            return None

    # ── public API ────────────────────────────────────────────────────────

    def launch(self, uri: str) -> bool:
        """
        Launch a roblox-player: URI on the sandbox desktop.

        Uses CreateProcessW with lpDesktop so the Roblox process (and its
        children) start on the hidden desktop. Can be called from any thread.
        """
        exe = self._get_protocol_handler()
        if not exe:
            print("[sandbox] Could not find Roblox protocol handler in registry.")
            return False

        si = STARTUPINFOW()
        si.cb = ctypes.sizeof(STARTUPINFOW)
        si.lpDesktop = self.DESKTOP_NAME

        pi = PROCESS_INFORMATION()

        cmd = f'"{exe}" {uri}'
        result = kernel32.CreateProcessW(
            None,                  # lpApplicationName
            cmd,                   # lpCommandLine
            None,                  # lpProcessAttributes
            None,                  # lpThreadAttributes
            False,                 # bInheritHandles
            0,                     # dwCreationFlags
            None,                  # lpEnvironment
            None,                  # lpCurrentDirectory
            ctypes.byref(si),
            ctypes.byref(pi),
        )

        if result:
            kernel32.CloseHandle(pi.hProcess)
            kernel32.CloseHandle(pi.hThread)
            self._roblox_hwnd = None  # will be found lazily
            return True
        else:
            print(f"[sandbox] CreateProcessW failed (error {ctypes.GetLastError()})")
            return False

    def send_key(self, vk: int, duration: float = 0.05):
        """Queue a key press to the sandbox desktop."""
        self._queue.put({"action": "send_key", "vk": vk, "duration": duration})

    def hold_key(self, vk: int, duration: float):
        """Queue a sustained key hold (key down → sleep → key up)."""
        self._queue.put({"action": "hold_key", "vk": vk, "duration": duration})

    def hold_keys(self, vk_list: list[int], duration: float):
        """Queue holding multiple keys simultaneously for a duration."""
        self._queue.put({"action": "hold_keys", "keys": vk_list, "duration": duration})

    def send_click(self, x: int, y: int, button: str = "left"):
        """Queue a mouse click to the sandbox desktop."""
        self._queue.put({"action": "send_click", "x": x, "y": y, "button": button})

    def get_roblox_hwnd(self) -> int | None:
        """Find the Roblox window handle on the sandbox desktop (blocking)."""
        # Drain stale results
        while not self._result_queue.empty():
            try:
                self._result_queue.get_nowait()
            except Empty:
                break

        self._queue.put({"action": "find_hwnd"})
        try:
            return self._result_queue.get(timeout=3)
        except Empty:
            return self._roblox_hwnd

    def peek(self, seconds: float = 15):
        """
        Switch the display to the sandbox desktop for *seconds* so you
        can see Roblox, then auto-switch back to your main desktop.
        """
        self._queue.put({"action": "peek", "seconds": seconds})

    def get_window_size(self) -> tuple[int, int] | None:
        """Get Roblox window client area (width, height). Thread-safe."""
        hwnd = self._roblox_hwnd
        if not hwnd:
            return None
        rect = wintypes.RECT()
        user32.GetClientRect(hwnd, ctypes.byref(rect))
        w = rect.right - rect.left
        h = rect.bottom - rect.top
        return (w, h) if w > 0 and h > 0 else None
