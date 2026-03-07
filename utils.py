import os
import ctypes
import ctypes.wintypes
import psutil
from pathlib import Path

from constants import PLAYER_EXE, CLIENT_SETTINGS_DIR


def get_roblox_base_path() -> Path:
    local_appdata = os.environ.get("LOCALAPPDATA", "")
    return Path(local_appdata) / "Roblox"


def get_roblox_versions_path() -> Path:
    return get_roblox_base_path() / "Versions"


def find_latest_player_version() -> Path | None:
    versions_dir = get_roblox_versions_path()
    if not versions_dir.exists():
        return None

    best_path = None
    best_mtime = 0

    for entry in versions_dir.iterdir():
        if not entry.is_dir() or not entry.name.startswith("version-"):
            continue
        exe = entry / PLAYER_EXE
        if exe.exists():
            mtime = exe.stat().st_mtime
            if mtime > best_mtime:
                best_mtime = mtime
                best_path = entry

    return best_path


def get_player_exe_path() -> Path | None:
    version_dir = find_latest_player_version()
    if version_dir is None:
        return None
    return version_dir / PLAYER_EXE


def get_client_settings_path() -> Path | None:
    version_dir = find_latest_player_version()
    if version_dir is None:
        return None
    cs_dir = version_dir / CLIENT_SETTINGS_DIR
    cs_dir.mkdir(exist_ok=True)
    return cs_dir


def find_roblox_processes() -> list[psutil.Process]:
    procs = []
    for p in psutil.process_iter(["name"]):
        try:
            if p.info["name"] and p.info["name"].lower() == PLAYER_EXE.lower():
                procs.append(p)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return procs


def is_roblox_running() -> bool:
    return len(find_roblox_processes()) > 0


def get_roblox_window_handle() -> int | None:
    user32 = ctypes.windll.user32

    # Try the known Roblox window class
    hwnd = user32.FindWindowW("WINDOWSCLIENT", None)
    if hwnd:
        return hwnd

    # Fallback: enumerate windows looking for "Roblox" in the title
    result = []

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def enum_callback(hwnd, _lparam):
        length = user32.GetWindowTextLengthW(hwnd)
        if length > 0:
            buf = ctypes.create_unicode_buffer(length + 1)
            user32.GetWindowTextW(hwnd, buf, length + 1)
            if "roblox" in buf.value.lower():
                result.append(hwnd)
        return True

    user32.EnumWindows(enum_callback, 0)
    return result[0] if result else None


def kill_roblox_processes():
    for p in find_roblox_processes():
        try:
            p.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
