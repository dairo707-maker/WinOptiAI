"""Native Win32 API bridge via ctypes for Windows 11 Build 26200+.

Provides verified, zero-dependency access to:
- DWM Acrylic backdrop & strict 0px sharp window corners (dwmapi.dll)
- OneDrive Cloud-Only / Reparse Point attribute inspection (kernel32.dll)
- Windows Restart Manager file-lock inspection (Rstrtmgr.dll)
- Process EcoQoS / Efficiency Mode throttling (kernel32.dll)
- Working Set RAM trimming (psapi.dll)
- NTFS Hardlink creation (kernel32.dll)
- Native Recycle Bin deletion & scoped UAC elevation (shell32.dll)
"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import os
from pathlib import Path
from typing import Iterable


IS_WINDOWS = os.name == "nt"

# Win32 File Attributes
INVALID_FILE_ATTRIBUTES = 0xFFFFFFFF
FILE_ATTRIBUTE_READONLY = 0x00000001
FILE_ATTRIBUTE_HIDDEN = 0x00000002
FILE_ATTRIBUTE_SYSTEM = 0x00000004
FILE_ATTRIBUTE_DIRECTORY = 0x00000010
FILE_ATTRIBUTE_REPARSE_POINT = 0x00000400
FILE_ATTRIBUTE_OFFLINE = 0x00001000
FILE_ATTRIBUTE_RECALL_ON_OPEN = 0x00040000
FILE_ATTRIBUTE_PINNED = 0x00080000
FILE_ATTRIBUTE_UNPINNED = 0x00100000
FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS = 0x00400000

CLOUD_ONLY_MASK = (
    FILE_ATTRIBUTE_OFFLINE
    | FILE_ATTRIBUTE_RECALL_ON_OPEN
    | FILE_ATTRIBUTE_UNPINNED
    | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS
)

# DWM Window Attributes (Windows 11 22H2+ / 24H2 / 25H2)
DWMWA_USE_IMMERSIVE_DARK_MODE = 20
DWMWA_WINDOW_CORNER_PREFERENCE = 33
DWMWA_BORDER_COLOR = 34
DWMWA_SYSTEMBACKDROP_TYPE = 38

DWMWCP_DONOTROUND = 1
DWMSBT_TRANSIENTWINDOW = 3  # Acrylic
DWMSBT_TABBEDWINDOW = 4     # Mica Alt

# Process access & EcoQoS constants
PROCESS_SET_QUOTA = 0x0100
PROCESS_SET_INFORMATION = 0x0200
PROCESS_QUERY_INFORMATION = 0x0400
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
PROCESS_VM_READ = 0x0010
PROCESS_POWER_THROTTLING_INFORMATION = 4
PROCESS_POWER_THROTTLING_CURRENT_VERSION = 1
PROCESS_POWER_THROTTLING_EXECUTION_SPEED = 0x1

IDLE_PRIORITY_CLASS = 0x00000040
BELOW_NORMAL_PRIORITY_CLASS = 0x00004000
NORMAL_PRIORITY_CLASS = 0x00000020

# Restart Manager constants
CCH_RM_MAX_APP_NAME = 255
CCH_RM_MAX_SVC_NAME = 63
RM_SESSION_KEY_LEN = 32
ERROR_SUCCESS = 0
ERROR_MORE_DATA = 234

# SHFileOperation constants
FO_DELETE = 3
FOF_SILENT = 0x0004
FOF_NOCONFIRMATION = 0x0010
FOF_ALLOWUNDO = 0x0040
FOF_NOERRORUI = 0x0400


class _PROCESS_POWER_THROTTLING_STATE(ctypes.Structure):
    _fields_ = [
        ("Version", wintypes.DWORD),
        ("ControlMask", wintypes.DWORD),
        ("StateMask", wintypes.DWORD),
    ]


class _RM_UNIQUE_PROCESS(ctypes.Structure):
    _fields_ = [
        ("dwProcessId", wintypes.DWORD),
        ("ProcessStartTime", wintypes.FILETIME),
    ]


class _RM_PROCESS_INFO(ctypes.Structure):
    _fields_ = [
        ("Process", _RM_UNIQUE_PROCESS),
        ("strAppName", wintypes.WCHAR * (CCH_RM_MAX_APP_NAME + 1)),
        ("strServiceShortName", wintypes.WCHAR * (CCH_RM_MAX_SVC_NAME + 1)),
        ("ApplicationType", wintypes.DWORD),
        ("AppStatus", wintypes.ULONG),
        ("TSSessionId", wintypes.DWORD),
        ("bRestartable", wintypes.BOOL),
    ]


class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [
        ("hwnd", wintypes.HWND),
        ("wFunc", wintypes.UINT),
        ("pFrom", wintypes.LPCWSTR),
        ("pTo", wintypes.LPCWSTR),
        ("fFlags", wintypes.WORD),
        ("fAnyOperationsAborted", wintypes.BOOL),
        ("hNameMappings", wintypes.LPVOID),
        ("lpszProgressTitle", wintypes.LPCWSTR),
    ]


def get_file_attributes(path: str | Path) -> int | None:
    """Return Win32 file attribute bitmask or None if inaccessible."""
    if not IS_WINDOWS:
        return None
    attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
    if attrs == INVALID_FILE_ATTRIBUTES:
        return None
    return int(attrs)


def attrs_is_cloud_only(attrs: int | None) -> bool:
    """Fast attribute-bitmask check avoiding an extra Win32 GetFileAttributesW call."""
    return bool(attrs & CLOUD_ONLY_MASK) if attrs is not None else False


def attrs_is_reparse_or_system(attrs: int | None) -> bool:
    """Fast attribute-bitmask check for junctions/symlinks or OS system files."""
    if attrs is None:
        return False
    return bool(attrs & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_SYSTEM))


def is_cloud_only_file(path: str | Path) -> bool:
    """Return True when a file is a OneDrive/cloud placeholder that must NEVER be hydrated."""
    return attrs_is_cloud_only(get_file_attributes(path))


def is_reparse_or_system_file(path: str | Path) -> bool:
    """Return True if path is a reparse point (junction/symlink) or hidden OS system file."""
    return attrs_is_reparse_or_system(get_file_attributes(path))


def get_locking_processes(paths: Iterable[str | Path]) -> list[dict[str, str | int]]:
    """Query Windows Restart Manager (Rstrtmgr.dll) for processes locking the given files.

    Returns a list of dicts: [{"pid": int, "app_name": str, "service_name": str}].
    """
    if not IS_WINDOWS:
        return []

    file_list = [str(Path(p)) for p in paths if Path(p).exists()]
    if not file_list:
        return []

    rstrtmgr = ctypes.WinDLL("Rstrtmgr.dll")
    session_handle = wintypes.DWORD(0)
    session_key = ctypes.create_unicode_buffer(RM_SESSION_KEY_LEN + 1)

    res = rstrtmgr.RmStartSession(ctypes.byref(session_handle), 0, session_key)
    if res != ERROR_SUCCESS:
        return []

    try:
        arr_type = wintypes.LPCWSTR * len(file_list)
        c_files = arr_type(*file_list)
        res = rstrtmgr.RmRegisterResources(
            session_handle,
            len(file_list),
            c_files,
            0,
            None,
            0,
            None,
        )
        if res != ERROR_SUCCESS:
            return []

        needed = wintypes.UINT(0)
        count = wintypes.UINT(0)
        reasons = wintypes.DWORD(0)

        res = rstrtmgr.RmGetList(
            session_handle,
            ctypes.byref(needed),
            ctypes.byref(count),
            None,
            ctypes.byref(reasons),
        )
        if res == ERROR_SUCCESS or needed.value == 0:
            return []
        if res != ERROR_MORE_DATA:
            return []

        buf_count = needed.value
        proc_buf = (_RM_PROCESS_INFO * buf_count)()
        count.value = buf_count
        res = rstrtmgr.RmGetList(
            session_handle,
            ctypes.byref(needed),
            ctypes.byref(count),
            proc_buf,
            ctypes.byref(reasons),
        )
        if res != ERROR_SUCCESS:
            return []

        lockers: list[dict[str, str | int]] = []
        seen_pids: set[int] = set()
        for idx in range(count.value):
            info = proc_buf[idx]
            pid = int(info.Process.dwProcessId)
            if pid in seen_pids:
                continue
            seen_pids.add(pid)
            lockers.append(
                {
                    "pid": pid,
                    "app_name": str(info.strAppName).strip(),
                    "service_name": str(info.strServiceShortName).strip(),
                }
            )
        return lockers
    finally:
        rstrtmgr.RmEndSession(session_handle)


def set_process_ecoqos(pid: int, enable: bool = True) -> bool:
    """Enable or disable Windows 11 EcoQoS (Efficiency Mode) for a target PID."""
    if not IS_WINDOWS or pid <= 4:
        return False

    kernel32 = ctypes.windll.kernel32
    handle = kernel32.OpenProcess(
        PROCESS_SET_INFORMATION | PROCESS_QUERY_LIMITED_INFORMATION,
        False,
        int(pid),
    )
    if not handle:
        return False

    try:
        state = _PROCESS_POWER_THROTTLING_STATE(
            Version=PROCESS_POWER_THROTTLING_CURRENT_VERSION,
            ControlMask=PROCESS_POWER_THROTTLING_EXECUTION_SPEED,
            StateMask=PROCESS_POWER_THROTTLING_EXECUTION_SPEED if enable else 0,
        )
        ok_throttle = bool(
            kernel32.SetProcessInformation(
                handle,
                PROCESS_POWER_THROTTLING_INFORMATION,
                ctypes.byref(state),
                ctypes.sizeof(state),
            )
        )
        target_prio = BELOW_NORMAL_PRIORITY_CLASS if enable else NORMAL_PRIORITY_CLASS
        ok_prio = bool(kernel32.SetPriorityClass(handle, target_prio))
        return ok_throttle or ok_prio
    finally:
        kernel32.CloseHandle(handle)


def trim_process_working_set(pid: int) -> bool:
    """Safely trim inactive memory pages of a process via EmptyWorkingSet."""
    if not IS_WINDOWS or pid <= 4:
        return False

    kernel32 = ctypes.windll.kernel32
    psapi = ctypes.windll.psapi
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    psapi.EmptyWorkingSet.argtypes = [wintypes.HANDLE]
    psapi.EmptyWorkingSet.restype = wintypes.BOOL

    handle = kernel32.OpenProcess(
        PROCESS_SET_QUOTA | PROCESS_QUERY_INFORMATION | PROCESS_VM_READ,
        False,
        int(pid),
    )
    if not handle:
        return False

    try:
        return bool(psapi.EmptyWorkingSet(handle))
    finally:
        kernel32.CloseHandle(handle)


def create_ntfs_hardlink(link_path: str | Path, existing_file: str | Path) -> bool:
    """Create an NTFS hardlink at link_path pointing to existing_file."""
    if not IS_WINDOWS:
        return False
    return bool(ctypes.windll.kernel32.CreateHardLinkW(str(link_path), str(existing_file), None))


def send_to_recycle_bin(path: str | Path) -> bool:
    """Send file or directory to the Windows Recycle Bin silently using SHFileOperationW."""
    if not IS_WINDOWS:
        return False
    target = str(Path(path).resolve()) + "\0\0"
    op = _SHFILEOPSTRUCTW(
        hwnd=None,
        wFunc=FO_DELETE,
        pFrom=target,
        pTo=None,
        fFlags=FOF_ALLOWUNDO | FOF_NOCONFIRMATION | FOF_SILENT | FOF_NOERRORUI,
        fAnyOperationsAborted=False,
        hNameMappings=None,
        lpszProgressTitle=None,
    )
    res = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    return res == 0 and not op.fAnyOperationsAborted


def apply_window_theme(hwnd: int, dark: bool = True) -> bool:
    """Apply Windows 11 Acrylic backdrop (dark or light) and strict 0px sharp corners via dwmapi.dll."""
    if not IS_WINDOWS or not hwnd:
        return False
    try:
        dwmapi = ctypes.windll.dwmapi
        dark_val = wintypes.DWORD(1 if dark else 0)
        dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(dark_val),
            ctypes.sizeof(dark_val),
        )
        corner_pref = wintypes.DWORD(DWMWCP_DONOTROUND)
        dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_WINDOW_CORNER_PREFERENCE,
            ctypes.byref(corner_pref),
            ctypes.sizeof(corner_pref),
        )
        # 0x00BBGGRR: subtle slate for dark, subtle cool grey for light
        border_color = wintypes.DWORD(0x002C2621 if dark else 0x00D0C8C0)
        dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_BORDER_COLOR,
            ctypes.byref(border_color),
            ctypes.sizeof(border_color),
        )
        backdrop = wintypes.DWORD(DWMSBT_TRANSIENTWINDOW)
        res = dwmapi.DwmSetWindowAttribute(
            wintypes.HWND(hwnd),
            DWMWA_SYSTEMBACKDROP_TYPE,
            ctypes.byref(backdrop),
            ctypes.sizeof(backdrop),
        )
        return res == 0
    except OSError:
        return False


def apply_obsidian_acrylic(hwnd: int) -> bool:
    """Backward-compatible helper applying dark Obsidian Acrylic 0px."""
    return apply_window_theme(hwnd, dark=True)


def is_user_admin() -> bool:
    """Return True when running with elevated UAC administrator privileges."""
    if not IS_WINDOWS:
        return False
    try:
        return bool(ctypes.windll.shell32.IsUserAnAdmin())
    except OSError:
        return False


def run_elevated_command(executable: str, arguments: str) -> bool:
    """Trigger native Windows UAC prompt cleanly without inheriting PyInstaller _MEI vars."""
    if not IS_WINDOWS:
        return False
    pyi_keys = (
        "_MEIPASS",
        "_MEIPASS2",
        "_PYI_ARCHIVE_FILE",
        "_PYI_APPLICATION_HOME_DIR",
        "_PYI_PARENT_PROCESS_LEVEL",
        "_PYI_SPLASH_IPC",
    )
    saved = {k: os.environ.pop(k) for k in pyi_keys if k in os.environ}
    try:
        rc = ctypes.windll.shell32.ShellExecuteW(
            None,
            "runas",
            executable,
            arguments,
            None,
            1,
        )
        return int(rc) > 32
    finally:
        os.environ.update(saved)


def reveal_in_explorer(path: str | Path) -> bool:
    """Open Windows Explorer highlighting the target file or folder."""
    if not IS_WINDOWS:
        return False
    import subprocess

    target = Path(path)
    if not target.exists():
        parent = target.parent
        if parent.exists():
            subprocess.Popen(["explorer.exe", str(parent)])
            return True
        return False
    if target.is_dir():
        subprocess.Popen(["explorer.exe", str(target)])
    else:
        subprocess.Popen(["explorer.exe", f"/select,{target}"])
    return True


class _DATA_BLOB(ctypes.Structure):
    _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_byte))]


def dpapi_protect(plaintext: bytes) -> bytes:
    """Encrypt secrets bound to the current Windows user profile via DPAPI (crypt32.dll)."""
    if not IS_WINDOWS:
        return plaintext
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(plaintext, len(plaintext))
    in_blob = _DATA_BLOB(len(plaintext), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptProtectData(
        ctypes.byref(in_blob),
        "WinOptiAI-OneDrive",
        None,
        None,
        None,
        0x01,  # CRYPTPROTECT_UI_FORBIDDEN
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError("DPAPI CryptProtectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def dpapi_unprotect(ciphertext: bytes) -> bytes:
    """Decrypt DPAPI-protected payload for the active Windows user profile."""
    if not IS_WINDOWS:
        return ciphertext
    crypt32 = ctypes.windll.crypt32
    kernel32 = ctypes.windll.kernel32
    buf = ctypes.create_string_buffer(ciphertext, len(ciphertext))
    in_blob = _DATA_BLOB(len(ciphertext), ctypes.cast(buf, ctypes.POINTER(ctypes.c_byte)))
    out_blob = _DATA_BLOB()
    ok = crypt32.CryptUnprotectData(
        ctypes.byref(in_blob),
        None,
        None,
        None,
        None,
        0x01,
        ctypes.byref(out_blob),
    )
    if not ok:
        raise OSError("DPAPI CryptUnprotectData failed")
    try:
        return ctypes.string_at(out_blob.pbData, out_blob.cbData)
    finally:
        kernel32.LocalFree(out_blob.pbData)


def dehydrate_onedrive_file(path: str | Path) -> tuple[bool, str]:
    """Mark a synced OneDrive file as 'Online-only' (+U -P) via SetFileAttributesW without deleting it."""
    if not IS_WINDOWS:
        return False, "Solo disponible en Windows"
    target = str(Path(path))
    attrs = get_file_attributes(target)
    if attrs is None:
        return False, "Archivo no accesible"
    if attrs & CLOUD_ONLY_MASK and not (attrs & FILE_ATTRIBUTE_PINNED):
        return True, "Ya se encuentra solo en la nube"

    new_attrs = (attrs & ~FILE_ATTRIBUTE_PINNED) | FILE_ATTRIBUTE_UNPINNED
    ok = bool(ctypes.windll.kernel32.SetFileAttributesW(target, wintypes.DWORD(new_attrs)))
    if not ok:
        return False, "No se pudo cambiar atributo Files On-Demand"
    return True, "Marcado como Solo en la nube"
