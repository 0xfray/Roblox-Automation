import os
import platform
import psutil
from pathlib import Path

from constants import PLAYER_EXE, CLIENT_SETTINGS_DIR

IS_WINDOWS = platform.system() == "Windows"

if IS_WINDOWS:
    import ctypes
    import ctypes.wintypes
else:
    ctypes = None  # type: ignore


def get_roblox_base_path() -> Path:
    if IS_WINDOWS:
        local_appdata = os.environ.get("LOCALAPPDATA", "")
        return Path(local_appdata) / "Roblox"
    # Linux: common Roblox/Wine paths
    home = Path.home()
    for candidate in [
        home / ".local" / "share" / "vinegar" / "roblox",
        home / ".var" / "app" / "org.vinegarhq.Sober" / "data" / "sober",
        home / ".wine" / "drive_c" / "users" / os.environ.get("USER", "") / "AppData" / "Local" / "Roblox",
    ]:
        if candidate.exists():
            return candidate
    return home / ".local" / "share" / "roblox"


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
    if not IS_WINDOWS:
        return None
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


# ── multi-instance helpers ─────────────────────────────────────────────────

# Roblox singleton names — both must be closed for multi-instance
_SINGLETON_NAMES = ["ROBLOX_singletonMutex", "ROBLOX_singletonEvent"]


def find_roblox_pids() -> set[int]:
    """Return set of PIDs for all running Roblox player processes."""
    pids = set()
    for p in find_roblox_processes():
        try:
            pids.add(p.pid)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return pids


def get_window_handle_for_pid(pid: int) -> int | None:
    """Find the main Roblox window handle for a specific process ID."""
    if not IS_WINDOWS:
        return None
    user32 = ctypes.windll.user32
    result = []

    @ctypes.WINFUNCTYPE(ctypes.wintypes.BOOL, ctypes.wintypes.HWND, ctypes.wintypes.LPARAM)
    def enum_callback(hwnd, _lparam):
        proc_id = ctypes.wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(proc_id))
        if proc_id.value == pid:
            class_buf = ctypes.create_unicode_buffer(64)
            user32.GetClassNameW(hwnd, class_buf, 64)
            if class_buf.value == "WINDOWSCLIENT":
                result.append(hwnd)
                return False
            length = user32.GetWindowTextLengthW(hwnd)
            if length > 0:
                title_buf = ctypes.create_unicode_buffer(length + 1)
                user32.GetWindowTextW(hwnd, title_buf, length + 1)
                if "roblox" in title_buf.value.lower():
                    result.append(hwnd)
                    return False
        return True

    user32.EnumWindows(enum_callback, 0)
    return result[0] if result else None


def kill_roblox_process(pid: int):
    """Kill a specific Roblox process by PID."""
    try:
        proc = psutil.Process(pid)
        proc.kill()
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        pass


def is_pid_alive(pid: int) -> bool:
    """Check if a specific process is still running."""
    try:
        proc = psutil.Process(pid)
        return proc.is_running() and proc.status() != psutil.STATUS_ZOMBIE
    except (psutil.NoSuchProcess, psutil.AccessDenied):
        return False


# ── Multi-instance: Singleton bypass ───────────────────────────────────────
#
# Roblox prevents multiple instances using two named kernel objects:
#   - ROBLOX_singletonMutex  (legacy mutex)
#   - ROBLOX_singletonEvent  (current event)
#
# When Roblox starts, it creates these objects. If they already exist
# (ERROR_ALREADY_EXISTS), it thinks another instance is running and exits.
#
# The correct approach (used by MultiBloxy, SingleTonEventCloser, etc.):
#   1. Let Roblox instance #1 launch normally
#   2. AFTER it's running, enumerate handles in its process using
#      NtQuerySystemInformation(SystemExtendedHandleInformation)
#   3. Find handles named ROBLOX_singletonMutex / ROBLOX_singletonEvent
#   4. Close them via DuplicateHandle(DUPLICATE_CLOSE_SOURCE)
#   5. Now launch instance #2 — it creates fresh singleton objects
#   6. Repeat steps 2-5 for more instances
#
# NOTE: Do NOT pre-create the mutex/event — that causes Roblox to see
# ERROR_ALREADY_EXISTS on startup and refuse to launch.


import threading as _threading


def _query_handle_name_with_timeout(ntdll, handle_value, timeout=1.0) -> str | None:
    """Query an object's name via NtQueryObject, with a timeout.

    NtQueryObject can hang indefinitely on certain handle types (named pipes,
    ALPC ports). Running it in a thread with a timeout prevents freezing.
    handle_value should be a ctypes.wintypes.HANDLE or int.
    """
    result = [None]

    class UNICODE_STRING(ctypes.Structure):
        _fields_ = [
            ("Length", ctypes.c_ushort),
            ("MaximumLength", ctypes.c_ushort),
            ("Buffer", ctypes.c_wchar_p),
        ]

    class OBJECT_NAME_INFO(ctypes.Structure):
        _fields_ = [("Name", UNICODE_STRING)]

    # Set argtypes for NtQueryObject
    ntdll.NtQueryObject.argtypes = [
        ctypes.wintypes.HANDLE, ctypes.c_ulong,
        ctypes.c_void_p, ctypes.c_ulong,
        ctypes.POINTER(ctypes.c_ulong),
    ]
    ntdll.NtQueryObject.restype = ctypes.c_long

    def _query():
        try:
            name_buf = ctypes.create_string_buffer(1024)
            ret_len = ctypes.c_ulong(0)
            h = ctypes.wintypes.HANDLE(handle_value) if isinstance(handle_value, int) else handle_value
            status = ntdll.NtQueryObject(h, 1, name_buf, 1024, ctypes.byref(ret_len))
            if status >= 0:
                info = OBJECT_NAME_INFO.from_buffer_copy(name_buf)
                if info.Name.Buffer:
                    result[0] = info.Name.Buffer
        except Exception:
            pass

    t = _threading.Thread(target=_query, daemon=True)
    t.start()
    t.join(timeout=timeout)
    return result[0]


def close_roblox_singleton_in_processes() -> int:
    """Close Roblox singleton handles in ALL running Roblox processes.

    Windows-only. On Linux, returns 0 (Roblox singleton doesn't apply).

    Uses SystemHandleInformation (class 16). The entry layout on 64-bit
    Windows is 24 bytes with PID as USHORT at offset 4 and handle as
    USHORT at offset 10. Queries handle names with a timeout to avoid
    hanging on pipe handles. Returns the number of handles closed.
    """
    if not IS_WINDOWS:
        return 0
    import struct as _struct

    kernel32 = ctypes.windll.kernel32
    ntdll = ctypes.windll.ntdll

    # CRITICAL: Set proper argtypes for 64-bit handle passing.
    # Without this, ctypes passes int as c_int (32-bit) which corrupts
    # HANDLE values on 64-bit Windows, causing ERROR_INVALID_HANDLE.
    HANDLE = ctypes.wintypes.HANDLE
    DWORD = ctypes.wintypes.DWORD
    BOOL = ctypes.wintypes.BOOL

    kernel32.DuplicateHandle.argtypes = [
        HANDLE, HANDLE, HANDLE, ctypes.POINTER(HANDLE), DWORD, BOOL, DWORD
    ]
    kernel32.DuplicateHandle.restype = BOOL
    kernel32.CloseHandle.argtypes = [HANDLE]
    kernel32.CloseHandle.restype = BOOL
    kernel32.OpenProcess.argtypes = [DWORD, BOOL, DWORD]
    kernel32.OpenProcess.restype = HANDLE
    kernel32.GetCurrentProcess.argtypes = []
    kernel32.GetCurrentProcess.restype = HANDLE

    DUPLICATE_CLOSE_SOURCE = 0x00000001
    DUPLICATE_SAME_ACCESS = 0x00000002
    PROCESS_DUP_HANDLE = 0x0040
    STATUS_INFO_LENGTH_MISMATCH = ctypes.c_long(0xC0000004).value
    SYSTEM_HANDLE_INFORMATION = 16

    roblox_pids = find_roblox_pids()
    if not roblox_pids:
        return 0

    # Build a set of PIDs truncated to 16 bits (USHORT in the struct)
    roblox_pid_set = {pid & 0xFFFF for pid in roblox_pids}

    # Open process handles for all Roblox processes
    process_handles: dict[int, int] = {}
    for pid in roblox_pids:
        h = kernel32.OpenProcess(PROCESS_DUP_HANDLE, False, pid)
        if h:
            process_handles[pid] = h

    if not process_handles:
        return 0

    # Map truncated PID → full PID → process handle
    pid16_to_handle: dict[int, int] = {}
    for pid, h in process_handles.items():
        pid16_to_handle[pid & 0xFFFF] = h

    closed = 0

    try:
        # Enumerate all system handles
        buf_size = 0x1000000  # 16 MB initial
        buf = None
        for _ in range(10):
            buf = ctypes.create_string_buffer(buf_size)
            return_length = ctypes.c_ulong(0)
            status = ntdll.NtQuerySystemInformation(
                SYSTEM_HANDLE_INFORMATION, buf, buf_size, ctypes.byref(return_length)
            )
            if status == STATUS_INFO_LENGTH_MISMATCH:
                buf_size = max(buf_size * 2, return_length.value + 0x100000)
                if buf_size > 0x10000000:  # 256 MB safety cap
                    return 0
                continue
            break
        if status != 0:
            return 0

        # Parse: ULONG NumberOfHandles at offset 0
        num_handles = _struct.unpack_from("<I", buf, 0)[0]
        data = buf.raw

        # Entry layout (24 bytes, confirmed on 64-bit Windows 10/11):
        #   offset 0:  4 bytes  padding/reserved
        #   offset 4:  USHORT   UniqueProcessId
        #   offset 6:  USHORT   CreatorBackTraceIndex
        #   offset 8:  UCHAR    ObjectTypeNumber
        #   offset 9:  UCHAR    HandleAttributes
        #   offset 10: USHORT   HandleValue
        #   offset 12: PVOID    Object (8 bytes on x64)
        #   offset 20: ULONG    GrantedAccess
        ENTRY_SIZE = 24
        BASE = 4  # skip NumberOfHandles

        for i in range(min(num_handles, 500000)):
            off = BASE + i * ENTRY_SIZE
            if off + ENTRY_SIZE > return_length.value:
                break

            pid16 = _struct.unpack_from("<H", data, off + 4)[0]

            # Fast filter: skip entries not belonging to Roblox
            if pid16 not in roblox_pid_set:
                continue

            handle_value = _struct.unpack_from("<H", data, off + 10)[0]
            proc_handle = pid16_to_handle.get(pid16)
            if not proc_handle:
                continue

            # Duplicate the handle into our process to query its name
            dup_handle = HANDLE()
            cur_proc = kernel32.GetCurrentProcess()
            ok = kernel32.DuplicateHandle(
                HANDLE(proc_handle), HANDLE(handle_value),
                cur_proc, ctypes.byref(dup_handle),
                DWORD(0), False, DWORD(DUPLICATE_SAME_ACCESS),
            )
            if not ok or not dup_handle.value:
                continue

            # Query object name WITH TIMEOUT (prevents hanging on pipe handles)
            name = _query_handle_name_with_timeout(ntdll, dup_handle.value, timeout=1.0)

            # Close our duplicate
            kernel32.CloseHandle(dup_handle)

            if name:
                for singleton_name in _SINGLETON_NAMES:
                    if singleton_name in name:
                        # Close the handle in the Roblox process
                        kernel32.DuplicateHandle(
                            HANDLE(proc_handle), HANDLE(handle_value),
                            HANDLE(0), None,
                            DWORD(0), False, DWORD(DUPLICATE_CLOSE_SOURCE),
                        )
                        closed += 1
                        break

        return closed

    finally:
        for h in process_handles.values():
            kernel32.CloseHandle(h)


def close_roblox_mutex() -> bool:
    """Close Roblox singleton handles to allow launching another instance.

    Call AFTER Roblox instance #1 is running, BEFORE launching instance #2.
    """
    roblox_pids = find_roblox_pids()
    if not roblox_pids:
        return True  # nothing running, nothing to close

    closed = close_roblox_singleton_in_processes()
    return closed > 0


# Legacy alias
acquire_roblox_singleton = lambda: True  # no-op, pre-create is counterproductive
