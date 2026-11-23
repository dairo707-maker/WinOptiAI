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
import threading
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

ES_CONTINUOUS = 0x80000000
ES_SYSTEM_REQUIRED = 0x00000001
SYSTEM_MEMORY_LIST_INFORMATION = 80
MEMORY_PURGE_STANDBY_LIST = 4
SE_PRIVILEGE_ENABLED = 0x00000002
TOKEN_ADJUST_PRIVILEGES = 0x0020
TOKEN_QUERY = 0x0008

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


# v0.5.4: en CARPETAS, OneDrive marca FILE_ATTRIBUTE_UNPINNED como politica ("liberar espacio")
# aunque la carpeta y su listado esten en disco. Listar una carpeta nunca descarga contenido;
# solo se omiten carpetas que requieren ir a la nube para enumerarse (RECALL_*/OFFLINE).
# Para ARCHIVOS se sigue usando CLOUD_ONLY_MASK completo (incluye UNPINNED).
CLOUD_ONLY_DIR_MASK = FILE_ATTRIBUTE_OFFLINE | FILE_ATTRIBUTE_RECALL_ON_OPEN | FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS


def attrs_skip_entry(attrs: int | None, is_dir: bool) -> bool:
    """True si un escaneo debe omitir la entrada: reparse/sistema, o nube segun sea archivo o carpeta."""
    if attrs is None:
        return False
    if attrs & (FILE_ATTRIBUTE_REPARSE_POINT | FILE_ATTRIBUTE_SYSTEM):
        return True
    return bool(attrs & (CLOUD_ONLY_DIR_MASK if is_dir else CLOUD_ONLY_MASK))


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


def set_process_io_priority(pid: int, low: bool = True) -> bool:
    """Set Windows I/O priority for a process (IOPRIO_VERYLOW vs IOPRIO_NORMAL)."""
    if not IS_WINDOWS or pid <= 4:
        return False
    try:
        import psutil

        proc = psutil.Process(int(pid))
        target = psutil.IOPRIO_VERYLOW if low else psutil.IOPRIO_NORMAL
        proc.ionice(target)
        return True
    except Exception:  # noqa: BLE001
        return False


def get_process_io_low(pid: int) -> bool:
    """Return True when the process is running at low/very-low I/O priority."""
    if not IS_WINDOWS or pid <= 4:
        return False
    try:
        import psutil

        return int(psutil.Process(int(pid)).ionice()) <= int(psutil.IOPRIO_LOW)
    except Exception:  # noqa: BLE001
        return False


def set_focus_keep_awake(active: bool) -> bool:
    """Prevent Windows idle sleep during active Focus Mode without locking display off."""
    if not IS_WINDOWS:
        return False
    try:
        flags = (ES_CONTINUOUS | ES_SYSTEM_REQUIRED) if active else ES_CONTINUOUS
        fn = ctypes.windll.kernel32.SetThreadExecutionState
        fn.argtypes = [wintypes.DWORD]
        fn.restype = wintypes.DWORD
        return bool(fn(wintypes.DWORD(flags)))
    except OSError:
        return False


def _enable_token_privilege(privilege_name: str) -> bool:
    if not IS_WINDOWS:
        return False

    class _LUID(ctypes.Structure):
        _fields_ = [("LowPart", wintypes.DWORD), ("HighPart", wintypes.LONG)]

    class _LUID_AND_ATTRIBUTES(ctypes.Structure):
        _fields_ = [("Luid", _LUID), ("Attributes", wintypes.DWORD)]

    class _TOKEN_PRIVILEGES(ctypes.Structure):
        _fields_ = [("PrivilegeCount", wintypes.DWORD), ("Privileges", _LUID_AND_ATTRIBUTES * 1)]

    advapi32 = ctypes.windll.advapi32
    kernel32 = ctypes.windll.kernel32
    token = wintypes.HANDLE()
    if not advapi32.OpenProcessToken(kernel32.GetCurrentProcess(), TOKEN_ADJUST_PRIVILEGES | TOKEN_QUERY, ctypes.byref(token)):
        return False
    try:
        luid = _LUID()
        if not advapi32.LookupPrivilegeValueW(None, privilege_name, ctypes.byref(luid)):
            return False
        tp = _TOKEN_PRIVILEGES()
        tp.PrivilegeCount = 1
        tp.Privileges[0].Luid = luid
        tp.Privileges[0].Attributes = SE_PRIVILEGE_ENABLED
        ok = bool(advapi32.AdjustTokenPrivileges(token, False, ctypes.byref(tp), 0, None, None))
        return ok and kernel32.GetLastError() == 0
    except OSError:
        return False
    finally:
        kernel32.CloseHandle(token)


def purge_standby_memory_list(allow_uac: bool = False) -> tuple[bool, str]:
    """Purge Windows Standby RAM cache cleanly via NtSetSystemInformation (requires Admin + privilege)."""
    if not IS_WINDOWS:
        return False, "Solo compatible con Windows"
    if not is_user_admin():
        if not allow_uac:
            return False, "Requiere Administrador (UAC) para depurar la lista Standby."
        import base64

        cs = (
            "using System; using System.Runtime.InteropServices; "
            "public class WinOptiMem { "
            "[DllImport(\"ntdll.dll\")] public static extern int NtSetSystemInformation(int c, ref int d, int l); "
            "[DllImport(\"advapi32.dll\", SetLastError=true)] static extern bool OpenProcessToken(IntPtr h, uint a, out IntPtr t); "
            "[DllImport(\"advapi32.dll\", SetLastError=true, CharSet=CharSet.Unicode)] static extern bool LookupPrivilegeValue(string s, string n, out long l); "
            "[DllImport(\"advapi32.dll\", SetLastError=true)] static extern bool AdjustTokenPrivileges(IntPtr t, bool d, ref TP n, int bl, IntPtr p, IntPtr rl); "
            "[StructLayout(LayoutKind.Sequential, Pack=1)] struct TP { public int C; public long L; public int A; } "
            "public static int Purge() { "
            "IntPtr t; if (!OpenProcessToken(System.Diagnostics.Process.GetCurrentProcess().Handle, 0x28, out t)) return -1; "
            "long l; if (!LookupPrivilegeValue(null, \"SeProfileSingleProcessPrivilege\", out l)) return -2; "
            "TP tp = new TP { C=1, L=l, A=2 }; AdjustTokenPrivileges(t, false, ref tp, 0, IntPtr.Zero, IntPtr.Zero); "
            "int cmd = 4; return NtSetSystemInformation(80, ref cmd, 4); } }"
        )
        ps_cmd = (
            f"Add-Type -TypeDefinition '{cs}'; "
            "$rc = [WinOptiMem]::Purge(); if ($rc -eq 0) { exit 0 } else { exit 2 }"
        )
        enc = base64.b64encode(ps_cmd.encode("utf-16le")).decode("ascii")
        ok = run_elevated_command("powershell.exe", f"-NoProfile -WindowStyle Hidden -EncodedCommand {enc}", track=False)
        if ok:
            return True, "Solicitud UAC de depuracion Standby lanzada."
        return False, "Autorizacion UAC cancelada."

    if not _enable_token_privilege("SeProfileSingleProcessPrivilege"):
        return False, "No se pudo habilitar SeProfileSingleProcessPrivilege."
    try:
        ntdll = ctypes.windll.ntdll
        ntdll.NtSetSystemInformation.argtypes = [ctypes.c_int, ctypes.POINTER(ctypes.c_int), ctypes.c_ulong]
        ntdll.NtSetSystemInformation.restype = ctypes.c_long
        cmd = ctypes.c_int(MEMORY_PURGE_STANDBY_LIST)
        st = int(ntdll.NtSetSystemInformation(SYSTEM_MEMORY_LIST_INFORMATION, ctypes.byref(cmd), ctypes.sizeof(cmd)))
        if st == 0:
            return True, "Lista Standby de Windows depurada (RAM cache liberada sin cerrar apps)."
        return False, f"NtSetSystemInformation devolvio codigo 0x{st & 0xFFFFFFFF:08X}."
    except OSError as exc:
        return False, f"Error depurando lista Standby: {exc}"


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


def recycle_sound_path() -> str:
    """v0.5.9: ruta del sonido "Vaciar Papelera" del esquema de sonidos de Windows del usuario.

    Usa el sonido asignado en el esquema activo; si el evento no tiene sonido (lo normal en
    Windows 11) usa el archivo oficial ``Media\\Windows Recycle.wav``. Solo queda en silencio si el
    usuario eligio el esquema "Sin sonidos" (``.None``).
    """
    if not IS_WINDOWS:
        return ""
    try:
        import winreg

        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"AppEvents\Schemes") as key:
                scheme, _ = winreg.QueryValueEx(key, "")
            if str(scheme).strip().lower() == ".none":
                return ""
        except OSError:
            pass
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"AppEvents\Schemes\Apps\Explorer\EmptyRecycleBin\.Current"
        ) as key:
            value, _ = winreg.QueryValueEx(key, "")
        value = os.path.expandvars(str(value or "").strip())
        if value and os.path.isfile(value):
            return value
    except OSError:
        pass
    fallback = os.path.join(os.environ.get("SystemRoot", r"C:\Windows"), "Media", "Windows Recycle.wav")
    return fallback if os.path.isfile(fallback) else ""


def play_recycle_sound() -> bool:
    """Reproducir (asincrono) el sonido de Papelera de Windows. Nunca bloquea ni falla."""
    path = recycle_sound_path()
    if not path:
        return False
    try:
        import winsound

        winsound.PlaySound(path, winsound.SND_FILENAME | winsound.SND_ASYNC | winsound.SND_NODEFAULT)
        return True
    except (RuntimeError, OSError, ImportError):
        return False


def animations_enabled() -> bool:
    """v0.5.9: respetar "Mostrar animaciones en Windows" (SPI_GETCLIENTAREAANIMATION)."""
    if not IS_WINDOWS:
        return True
    try:
        value = wintypes.BOOL(True)
        ok = ctypes.windll.user32.SystemParametersInfoW(0x1042, 0, ctypes.byref(value), 0)
        return bool(value.value) if ok else True
    except (OSError, AttributeError):
        return True


RESTART_NO_PATCH = 0x4
RESTART_NO_REBOOT = 0x8


def register_application_restart(arguments: str) -> bool:
    """v0.5.3: pedir a Windows (WER) que reabra la app tras un cierre inesperado o un bloqueo,
    como hacen Office y otros programas tipicos. No se reinicia por actualizaciones ni reinicios
    del sistema. Windows solo lo hace si la app llevaba al menos 60 s abierta."""
    if not IS_WINDOWS:
        return False
    try:
        fn = ctypes.windll.kernel32.RegisterApplicationRestart
        fn.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        fn.restype = ctypes.c_long
        return fn(arguments, RESTART_NO_PATCH | RESTART_NO_REBOOT) == 0
    except (OSError, AttributeError):
        return False


class _ShellExecuteInfoW(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD),
        ("fMask", wintypes.ULONG),
        ("hwnd", wintypes.HWND),
        ("lpVerb", wintypes.LPCWSTR),
        ("lpFile", wintypes.LPCWSTR),
        ("lpParameters", wintypes.LPCWSTR),
        ("lpDirectory", wintypes.LPCWSTR),
        ("nShow", ctypes.c_int),
        ("hInstApp", wintypes.HINSTANCE),
        ("lpIDList", ctypes.c_void_p),
        ("lpClass", wintypes.LPCWSTR),
        ("hkeyClass", wintypes.HKEY),
        ("dwHotKey", wintypes.DWORD),
        ("hIconOrMonitor", wintypes.HANDLE),
        ("hProcess", wintypes.HANDLE),
    ]


# v0.5.9: procesos lanzados por la app (consolas elevadas: DISM, SFC, CHKDSK, TRIM...).
_TRACKED_CHILDREN: list[tuple[int, str]] = []
_TRACK_LOCK = threading.Lock()

# Programas externos que el usuario abre desde la app y que NO deben cerrarse al salir.
EXTERNAL_APP_NAMES: frozenset[str] = frozenset(
    {
        "explorer.exe", "msedge.exe", "chrome.exe", "firefox.exe", "brave.exe", "opera.exe",
        "systemsettings.exe", "applicationframehost.exe", "winoptiai-setup.exe",
    }
)
_PROTECTED_CHILD_PIDS: set[int] = set()  # p. ej. el puente del actualizador


def _kernel32_proc() -> ctypes.WinDLL:
    k32 = ctypes.WinDLL("kernel32", use_last_error=True)
    k32.GetProcessId.argtypes = [wintypes.HANDLE]
    k32.GetProcessId.restype = wintypes.DWORD
    k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    k32.WaitForSingleObject.restype = wintypes.DWORD
    k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    k32.TerminateProcess.restype = wintypes.BOOL
    k32.CloseHandle.argtypes = [wintypes.HANDLE]
    k32.CloseHandle.restype = wintypes.BOOL
    return k32


def _protect_and_close_process_handle(handle: int | None) -> None:
    """Register spawned process PID as protected from shutdown cleanup and close its handle."""
    if not handle:
        return
    k32 = _kernel32_proc()
    h = wintypes.HANDLE(int(handle))
    try:
        pid = int(k32.GetProcessId(h))
        if pid:
            protect_child_pid(pid)
    finally:
        k32.CloseHandle(h)


def _track_child(handle: int, label: str) -> None:
    with _TRACK_LOCK:
        _TRACKED_CHILDREN.append((int(handle), label))


def shell_open_protected(file: str, params: str, directory: str | None = None, show: int = 0) -> bool:
    """Lanzar un proceso que debe sobrevivir al cierre de la app (actualizador) y protegerlo."""
    if not IS_WINDOWS:
        return False
    info = _ShellExecuteInfoW()
    info.cbSize = ctypes.sizeof(_ShellExecuteInfoW)
    info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
    info.lpVerb = "open"
    info.lpFile = file
    info.lpParameters = params
    info.lpDirectory = directory
    info.nShow = show
    if not ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)):
        return False
    _protect_and_close_process_handle(info.hProcess)
    return True


def protect_child_pid(pid: int) -> None:
    """Excluir un proceso hijo del cierre total (actualizador que debe seguir tras salir)."""
    _PROTECTED_CHILD_PIDS.add(int(pid))


def running_tracked_children() -> list[str]:
    """Etiquetas de las consolas lanzadas por la app que siguen abiertas."""
    if not IS_WINDOWS:
        return []
    alive: list[str] = []
    k32 = _kernel32_proc()
    with _TRACK_LOCK:
        for handle, label in _TRACKED_CHILDREN:
            if k32.WaitForSingleObject(wintypes.HANDLE(handle), 0) == 0x102:  # WAIT_TIMEOUT
                alive.append(label)
    return alive


def terminate_app_child_processes() -> dict[str, int]:
    """v0.5.9: cerrar TODO lo que inicio la app (consolas elevadas y procesos descendientes).

    Se respetan los programas externos abiertos para el usuario (navegador, Explorador,
    Configuracion), el actualizador y el relanzamiento elevado UAC.
    """
    closed = 0
    failed = 0
    if IS_WINDOWS:
        with _TRACK_LOCK:
            tracked = list(_TRACKED_CHILDREN)
            _TRACKED_CHILDREN.clear()
        k32 = _kernel32_proc()
        for handle, _label in tracked:
            h = wintypes.HANDLE(handle)
            if k32.WaitForSingleObject(h, 0) == 0x102:
                if k32.TerminateProcess(h, 1):
                    closed += 1
                else:
                    failed += 1
            k32.CloseHandle(h)
    try:
        import psutil

        me = psutil.Process(os.getpid())
        keep: set[int] = set()
        for pid in list(_PROTECTED_CHILD_PIDS):
            try:
                keep.add(pid)
                keep.update(c.pid for c in psutil.Process(pid).children(recursive=True))
            except psutil.Error:
                continue

        def _is_protected(proc: psutil.Process) -> bool:
            if proc.pid in keep:
                return True
            try:
                for anc in proc.parents():
                    if anc.pid == me.pid:
                        break
                    if anc.pid in keep:
                        keep.add(proc.pid)
                        return True
            except psutil.Error:
                pass
            return False

        for child in me.children(recursive=True):
            try:
                cname = child.name().lower()
                if (
                    _is_protected(child)
                    or cname in EXTERNAL_APP_NAMES
                    or (cname in {"conhost.exe", "openconsole.exe"} and child.ppid() == me.pid)
                ):
                    continue
                child.kill()
                closed += 1
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                failed += 1
    except Exception:  # noqa: BLE001
        pass
    return {"closed": closed, "failed": failed}


def run_elevated_command(
    executable: str,
    arguments: str,
    *,
    track: bool = True,
    directory: str | None = None,
) -> bool:
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
    # v0.5.1: ShellExecuteW puede invocarse desde un hilo QThreadPool (acciones de auditoria
    # sin bloquear la UI durante UAC). Microsoft exige COM inicializado (STA) en ese hilo.
    com_initialized = False
    try:
        hr = ctypes.windll.ole32.CoInitializeEx(None, 0x2 | 0x4)  # APARTMENTTHREADED | DISABLE_OLE1DDE
        com_initialized = hr in (0, 1)  # S_OK / S_FALSE -> requiere CoUninitialize balanceado
    except (AttributeError, OSError):
        com_initialized = False
    try:
        # v0.5.9: ShellExecuteExW con SEE_MASK_NOCLOSEPROCESS para conservar consolas elevadas
        # (DISM/SFC/CHKDSK) y cerrarlas al salir. Cuando track=False (relanzamiento Admin de la
        # propia app), se protege el PID nuevo para que el cierre saliente NO lo termine.
        info = _ShellExecuteInfoW()
        info.cbSize = ctypes.sizeof(_ShellExecuteInfoW)
        info.fMask = 0x00000040  # SEE_MASK_NOCLOSEPROCESS
        info.lpVerb = "runas"
        info.lpFile = executable
        info.lpParameters = arguments
        if directory:
            info.lpDirectory = directory
        info.nShow = 1
        ok = bool(ctypes.windll.shell32.ShellExecuteExW(ctypes.byref(info)))
        if ok and info.hProcess:
            if track:
                _track_child(info.hProcess, f"{os.path.basename(executable)} {arguments[:80]}")
            else:
                _protect_and_close_process_handle(info.hProcess)
        return ok
    finally:
        if com_initialized:
            try:
                ctypes.windll.ole32.CoUninitialize()
            except (AttributeError, OSError):
                pass
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


def get_foreground_pid() -> int | None:
    """Return PID of the active foreground window so AI Boost never trims user focus."""
    if not IS_WINDOWS:
        return None
    try:
        hwnd = ctypes.windll.user32.GetForegroundWindow()
        if not hwnd:
            return None
        pid = wintypes.DWORD(0)
        ctypes.windll.user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value) if pid.value > 4 else None
    except OSError:
        return None


def is_windows_taskbar_light_theme() -> bool:
    """Return True when the Windows taskbar/tray uses light mode (SystemUsesLightTheme == 1)."""
    if not IS_WINDOWS:
        return False
    import winreg

    subkey = r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize"
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, subkey) as key:
            for val_name in ("SystemUsesLightTheme", "AppsUseLightTheme"):
                try:
                    val, _ = winreg.QueryValueEx(key, val_name)
                    return int(val) == 1
                except FileNotFoundError:
                    continue
    except OSError:
        pass
    return False


def has_windows_reboot_pending() -> bool:
    """Return True if CBS, Windows Update, or Session Manager reports a pending reboot."""
    if not IS_WINDOWS:
        return False
    import winreg

    checks = (
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\Component Based Servicing\RebootPending",
        r"SOFTWARE\Microsoft\Windows\CurrentVersion\WindowsUpdate\Auto Update\RebootRequired",
    )
    for subkey in checks:
        try:
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subkey):
                return True
        except OSError:
            pass
    try:
        sm = r"SYSTEM\CurrentControlSet\Control\Session Manager"
        with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, sm) as key:
            val, _ = winreg.QueryValueEx(key, "PendingFileRenameOperations")
            if val:
                return True
    except OSError:
        pass
    return False
