"""Shared last-used timestamp formatting and Windows application usage telemetry (BAM / Prefetch / live processes)."""

from __future__ import annotations

import codecs
from datetime import datetime
import os
from pathlib import Path
import re
import time
import psutil

from .win32_bridge import IS_WINDOWS

_EPOCH_DIFF_1601_1970 = 116_444_736_000_000_000  # 100-ns intervals between 1601-01-01 and 1970-01-01
_NORM_PREFIX = "__norm:"

_GENERIC_APP_TOKENS: frozenset[str] = frozenset(
    {
        "microsoft",
        "windows",
        "seiko",
        "epson",
        "hp",
        "lenovo",
        "intel",
        "amd",
        "nvidia",
        "realtek",
        "adobe",
        "google",
        "python",
        "java",
        "oracle",
        "apple",
        "arcgis",
        "office",
        "autodesk",
        "jetbrains",
        "system",
        "update",
        "updater",
        "setup",
        "driver",
        "drivers",
        "runtime",
        "service",
        "helper",
        "plugin",
        "launcher",
        "installer",
        "tools",
        "common",
        "program",
        "software",
        "client",
        "desktop",
        "viewer",
        "reader",
        "player",
        "browser",
        "editor",
        "ide",
        "app",
    }
)

_AUMID_NOISE_SEGMENTS: frozenset[str] = frozenset(
    {"com", "org", "net", "io", "app", "desktop", "exe", "bin", "electron", "win", "win32", "win64", "x64", "user",
     "userdata", "default", "systemprofile"}
)

# v0.6.3: navegadores registran un AUMID por perfil ('Chrome.UserData.Profile1', 'MSEdge.edgeX.Default').
# Todos cuentan como uso del navegador; WebView2 NO es uso de Edge (lo abren otras apps).
_BROWSER_AUMID_HEADS: frozenset[str] = frozenset({"chrome", "msedge", "brave", "firefox", "opera", "vivaldi"})
_IGNORED_AUMID_HEADS: frozenset[str] = frozenset({"msedgewebview", "microsoft.windows.explorer_recommendationsfiles"})

# Complementos/instaladores de una suite no heredan la fecha de uso de la suite.
_COMPONENT_MARKERS: tuple[str, ...] = (
    "add-in", "addin", "plugin", "plug-in", "installer", "runtime", "language pack", "paquete de idioma", "redistributable",
)

# v0.6.3: suites cuyo nombre en "Programas" no coincide con sus ejecutables.
_SUITE_ALIASES: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("microsoft 365", ("excel", "winword", "powerpnt", "outlook", "onenote", "msaccess", "mspub")),
    ("office", ("excel", "winword", "powerpnt", "outlook", "onenote", "msaccess", "mspub")),
    ("stata", ("statamp", "statase", "statabe", "statamp64", "statase64", "statamp1764bit")),
    ("power bi", ("pbidesktop",)),
    ("powerbi", ("pbidesktop",)),
    ("zoom", ("zoom", "zoomuszoomvideomeetings")),
    ("teams", ("msteams", "teams")),
    ("whatsapp", ("whatsappdesktop", "whatsapp")),
)

_BROAD_INSTALL_DIRS: frozenset[str] = frozenset(
    {
        r"c:\windows",
        r"c:\windows\system32",
        r"c:\windows\syswow64",
        r"c:\program files",
        r"c:\program files (x86)",
        r"c:\program files\common files",
        r"c:\program files (x86)\common files",
        r"c:\programdata",
        r"c:\users",
    }
)


def format_last_used(ts: float | None, now: float | None = None) -> str:
    """Format an epoch timestamp using mixed human/ISO style ('Hoy', 'Ayer', 'Hace N d', 'YYYY-MM-DD')."""
    if ts is None or float(ts) <= 0.0:
        return "Sin registro"
    cur = time.time() if now is None else float(now)
    val = float(ts)
    try:
        dt_val = datetime.fromtimestamp(val)
        dt_now = datetime.fromtimestamp(cur)
    except (OSError, OverflowError, ValueError):
        return "Sin registro"

    day_diff = (dt_now.date() - dt_val.date()).days
    if day_diff <= 0:
        return "Hoy"
    if day_diff == 1:
        return "Ayer"
    if day_diff < 30:
        return f"Hace {day_diff} d"
    return dt_val.strftime("%Y-%m-%d")


def format_last_used_time(ts: float | None, now: float | None = None) -> str:
    """Format with time of day when today (used for live running processes), otherwise format_last_used."""
    if ts is None or float(ts) <= 0.0:
        return "Sin registro"
    cur = time.time() if now is None else float(now)
    val = float(ts)
    try:
        dt_val = datetime.fromtimestamp(val)
        dt_now = datetime.fromtimestamp(cur)
    except (OSError, OverflowError, ValueError):
        return "Sin registro"
    if dt_val.date() == dt_now.date():
        return f"Hoy {dt_val.strftime('%H:%M')}"
    return format_last_used(val, now=cur)


def format_app_last_used(
    last_used_ts: float | None,
    install_date_ts: float | None = 0.0,
    now: float | None = None,
) -> str:
    """Format real execution timestamp, falling back honestly to 'Inst. YYYY-MM-DD' or 'Sin registro'."""
    if last_used_ts is not None and float(last_used_ts) > 0.0:
        return format_last_used(last_used_ts, now=now)
    if install_date_ts is not None and float(install_date_ts) > 0.0:
        try:
            dt_inst = datetime.fromtimestamp(float(install_date_ts))
            return f"Inst. {dt_inst.strftime('%Y-%m-%d')}"
        except (OSError, OverflowError, ValueError):
            pass
    return "Sin registro"


def file_last_used_ts(st: os.stat_result | None) -> float:
    """Return max(st_atime, st_mtime) to handle volumes with NtfsDisableLastAccessUpdate enabled."""
    if st is None:
        return 0.0
    atime = float(getattr(st, "st_atime", 0.0) or 0.0)
    mtime = float(getattr(st, "st_mtime", 0.0) or 0.0)
    return max(atime, mtime, 0.0)


def parse_iso_timestamp(text: str | None) -> float:
    """Parse common ISO-8601 or 'YYYY-MM-DD HH:MM:SS' strings to Unix epoch seconds."""
    raw = (text or "").strip()
    if not raw or raw in ("N/D", "--"):
        return 0.0
    try:
        norm = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        dt = datetime.fromisoformat(norm)
        return float(dt.timestamp())
    except ValueError:
        pass
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
        try:
            return float(datetime.strptime(raw[:19], fmt).timestamp())
        except ValueError:
            continue
    return 0.0


def filetime_bytes_to_epoch(raw: bytes) -> float:
    """Convert Windows 8-byte little-endian FILETIME (100ns since 1601) into Unix epoch seconds."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < 8:
        return 0.0
    ft = int.from_bytes(raw[:8], "little", signed=False)
    if ft <= _EPOCH_DIFF_1601_1970:
        return 0.0
    ts = (ft - _EPOCH_DIFF_1601_1970) / 10_000_000.0
    if ts > time.time() + 86400 * 365:
        return 0.0
    return ts


def _norm_alnum(text: str) -> str:
    """Normalize text for exact app matching while keeping '++' distinct from plain names."""
    s = (text or "").lower().replace("++", "plusplus")
    s = re.sub(r"[®™©]", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


def _known_folder_map() -> dict[str, str]:
    windir = os.environ.get("WINDIR", r"C:\Windows")
    pf64 = os.environ.get("ProgramW6432") or os.environ.get("ProgramFiles") or r"C:\Program Files"
    pf86 = os.environ.get("ProgramFiles(x86)") or r"C:\Program Files (x86)"
    local = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
    roaming = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
    profile = os.environ.get("USERPROFILE") or str(Path.home())
    progdata = os.environ.get("PROGRAMDATA") or r"C:\ProgramData"
    return {
        "{6D809377-6AF0-444B-8957-A3773F02200E}": pf64,
        "{905E63B6-C1BF-494E-B29C-65B732D3D21A}": os.environ.get("ProgramFiles") or pf64,
        "{7C5A40EF-A0FB-4BFC-874A-C0F2E0B9FA8E}": pf86,
        "{F1B32785-6FBA-4FCF-9D55-7B8E7F157091}": local,
        "{3EB685DB-65F9-4CF6-A03A-E3EF65729F3D}": roaming,
        "{1AC14E77-02E7-4E5D-B744-2EB1AE5198B7}": f"{windir}\\System32",
        "{F38BF404-1D43-42F2-9305-67DE0B28FC23}": windir,
        "{5E6C858F-0E22-4760-9AFE-EA3317B67173}": profile,
        "{0139D44E-6AFE-49F2-8690-3DAFCAE6FFB8}": f"{progdata}\\Microsoft\\Windows\\Start Menu\\Programs",
        "{A77F5D77-2E2B-44C3-A6A2-ABA601054A51}": f"{roaming}\\Microsoft\\Windows\\Start Menu\\Programs",
        "{9E3995AB-1F9C-4F13-B827-48B24B6C7174}": f"{roaming}\\Microsoft\\Internet Explorer\\Quick Launch\\User Pinned",
    }


def decode_userassist_name(encoded: str) -> str:
    """ROT13-decode a UserAssist registry value name and expand standard KNOWNFOLDERID prefixes."""
    if not encoded:
        return ""
    return expand_known_folder(codecs.decode(encoded, "rot_13"))


def expand_known_folder(name: str) -> str:
    """Expand a leading '{KNOWNFOLDERID}' (UserAssist / JumplistData) into its real folder path."""
    dec = (name or "").replace("/", "\\").strip()
    if dec.startswith("{") and len(dec) >= 38:
        prefix = dec[:38].upper()
        base_dir = _known_folder_map().get(prefix)
        if base_dir:
            rest = dec[38:].lstrip("\\")
            return f"{base_dir.rstrip(chr(92))}\\{rest}" if rest else base_dir
    return dec


def parse_userassist_blob(raw: bytes) -> float:
    """Extract Windows last-run FILETIME (bytes 60..68) from a 72+ byte UserAssist v5 value."""
    if not isinstance(raw, (bytes, bytearray)) or len(raw) < 72:
        return 0.0
    return filetime_bytes_to_epoch(raw[60:68])


def _store_ts(usage: dict[str, float], key: str, ts: float) -> None:
    if key and ts > usage.get(key, 0.0):
        usage[key] = ts


def _record_usage_key(usage: dict[str, float], name_or_path: str, ts: float) -> None:
    if ts <= 0.0 or not name_or_path:
        return
    clean = name_or_path.replace("/", "\\").strip().lower()
    if not clean:
        return
    base = clean.rsplit("\\", 1)[-1]
    stem = base[:-4] if base.endswith(".exe") else base
    for key in (clean, base, stem):
        _store_ts(usage, key, ts)
    norm = _norm_alnum(stem)
    if len(norm) >= 4:
        _store_ts(usage, f"{_NORM_PREFIX}{norm}", ts)


def _record_userassist_entry(usage: dict[str, float], decoded_name: str, ts: float) -> None:
    if ts <= 0.0 or not decoded_name:
        return
    up = decoded_name.upper()
    if up.startswith(("UEME_", "MICROSOFT.AUTOGENERATED.")):
        return
    low = decoded_name.lower()
    if "\\" not in low and "/" not in low:
        # AUMID / AppUserModelId (e.g. 'com.mdhero.app', 'electron.app.Antigravity', 'Pkg_hash!App')
        no_bang = low.split("!", 1)[0]
        no_hash = re.sub(r"_[a-z0-9]{13}$", "", no_bang)
        head = no_hash.split(".", 1)[0]
        if head in _IGNORED_AUMID_HEADS or no_hash in _IGNORED_AUMID_HEADS:
            return
        if head in _BROWSER_AUMID_HEADS:
            # Cualquier perfil del navegador cuenta como uso del navegador (y nada mas).
            _store_ts(usage, f"{_NORM_PREFIX}{head}", ts)
            return
        norm_full = _norm_alnum(no_hash)
        if len(norm_full) >= 4:
            _store_ts(usage, f"{_NORM_PREFIX}{norm_full}", ts)
        if "." in no_hash:
            parts = [
                p for p in no_hash.split(".")
                if p and p not in _AUMID_NOISE_SEGMENTS and not p.isdigit() and not re.fullmatch(r"profile\d*", p)
            ]
            if parts:
                joined = _norm_alnum("".join(parts))
                if len(joined) >= 4:
                    _store_ts(usage, f"{_NORM_PREFIX}{joined}", ts)
                tail = _norm_alnum(parts[-1])
                if len(tail) >= 4 and tail not in _GENERIC_APP_TOKENS:
                    _store_ts(usage, f"{_NORM_PREFIX}{tail}", ts)
        return

    clean = low.replace("/", "\\").strip()
    base = clean.rsplit("\\", 1)[-1]
    if base.endswith(".lnk"):
        lnk_stem = base[:-4].strip()
        if lnk_stem:
            _store_ts(usage, lnk_stem, ts)
            norm_lnk = _norm_alnum(lnk_stem)
            if len(norm_lnk) >= 4:
                _store_ts(usage, f"{_NORM_PREFIX}{norm_lnk}", ts)
        target = resolve_lnk_target(decoded_name)
        if target and target.lower().endswith(".exe"):
            _record_usage_key(usage, target, ts)
        return
    _record_usage_key(usage, clean, ts)


_LNK_CACHE: dict[str, str] = {}


def resolve_lnk_target(lnk_path: str) -> str:
    """Return the local target path of a Windows .lnk (MS-SHLLINK LinkInfo), or '' if unknown.

    Lector minimo sin pywin32 ni COM: solo lee la cabecera y LinkInfo.LocalBasePath. Los accesos
    "anunciados" de MSI (sin LinkInfo) devuelven ''.
    """
    key = (lnk_path or "").lower()
    if key in _LNK_CACHE:
        return _LNK_CACHE[key]
    result = ""
    try:
        with open(lnk_path, "rb") as fh:
            data = fh.read(65536)
        if len(data) >= 76 and int.from_bytes(data[0:4], "little") == 0x4C:
            flags = int.from_bytes(data[20:24], "little")
            pos = 76
            if flags & 0x1:  # HasLinkTargetIDList
                pos += 2 + int.from_bytes(data[pos:pos + 2], "little")
            if flags & 0x2:  # HasLinkInfo
                li = pos
                li_hdr = int.from_bytes(data[li + 4:li + 8], "little")
                li_flags = int.from_bytes(data[li + 8:li + 12], "little")
                if li_flags & 0x1:  # VolumeIDAndLocalBasePath
                    if li_hdr >= 0x24:
                        off_u = int.from_bytes(data[li + 28:li + 32], "little")
                        raw = data[li + off_u:]
                        end = raw.find(b"\x00\x00")
                        while end % 2:
                            end = raw.find(b"\x00\x00", end + 1)
                        result = raw[:end].decode("utf-16-le", "ignore")
                    else:
                        off = int.from_bytes(data[li + 16:li + 20], "little")
                        raw = data[li + off:]
                        result = raw[: raw.find(b"\x00")].decode("mbcs" if IS_WINDOWS else "latin-1", "ignore")
    except (OSError, ValueError, LookupError):
        result = ""
    _LNK_CACHE[key] = result.strip()
    return _LNK_CACHE[key]


def visible_window_pids() -> set[int]:
    """PIDs que tienen una ventana principal visible (apps que la persona esta usando ahora).

    v0.6.3: antes cualquier proceso vivo marcaba la app como "Hoy"; servicios y procesos de fondo
    (antivirus, Lenovo, WebView2, actualizadores) daban falsos "Hoy" en 21 aplicaciones.
    """
    pids: set[int] = set()
    if not IS_WINDOWS:
        return pids
    try:
        import ctypes
        from ctypes import wintypes

        user32 = ctypes.windll.user32
        enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)
        user32.GetWindow.restype = wintypes.HWND
        user32.GetWindow.argtypes = [wintypes.HWND, wintypes.UINT]

        def _cb(hwnd, _lparam):
            if user32.IsWindowVisible(hwnd) and not user32.GetWindow(hwnd, 4):  # GW_OWNER
                if user32.GetWindowTextLengthW(hwnd) > 0:
                    pid = wintypes.DWORD()
                    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
                    if pid.value:
                        pids.add(int(pid.value))
            return True

        user32.EnumWindows(enum_proc(_cb), 0)
    except Exception:  # noqa: BLE001
        pass
    return pids


def _read_jumplist_data(usage: dict[str, float]) -> None:
    """HKCU\\...\\Search\\JumplistData: ultimo arranque por AUMID o ruta (sin UAC, mas fresco que UserAssist)."""
    import winreg

    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Search\JumplistData"
        ) as k:
            idx = 0
            while True:
                try:
                    v_name, v_val, _v_type = winreg.EnumValue(k, idx)
                    idx += 1
                except OSError:
                    break
                if isinstance(v_val, int):
                    ts = filetime_bytes_to_epoch(int(v_val).to_bytes(8, "little", signed=False))
                else:
                    ts = filetime_bytes_to_epoch(v_val)
                if ts > 0.0 and v_name:
                    _record_userassist_entry(usage, expand_known_folder(str(v_name)), ts)
    except (OSError, OverflowError):
        pass


def read_windows_app_usage_map() -> dict[str, float]:
    """Read last-executed timestamps from live processes, BAM, HKCU UserAssist (no UAC), and Prefetch."""
    usage: dict[str, float] = {}
    now = time.time()

    # 1. Apps abiertas AHORA con ventana visible (los procesos de fondo no son "uso")
    try:
        window_pids = visible_window_pids() if IS_WINDOWS else None
        for proc in psutil.process_iter(attrs=["pid", "name", "exe", "create_time"]):
            info = proc.info
            if window_pids is not None and int(info.get("pid") or 0) not in window_pids:
                continue
            ts = now
            if info.get("name"):
                _record_usage_key(usage, str(info["name"]), ts)
            if info.get("exe"):
                _record_usage_key(usage, str(info["exe"]), ts)
    except Exception:
        pass

    if not IS_WINDOWS:
        return usage

    import winreg

    # 2. Windows Background Activity Moderator (BAM) registry timestamps
    try:
        for subroot in (
            r"SYSTEM\CurrentControlSet\Services\bam\State\UserSettings",
            r"SYSTEM\CurrentControlSet\Services\dam\State\UserSettings",
        ):
            try:
                with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, subroot) as rk:
                    idx = 0
                    while True:
                        try:
                            sid = winreg.EnumKey(rk, idx)
                            idx += 1
                        except OSError:
                            break
                        try:
                            with winreg.OpenKey(rk, sid) as sk:
                                v_idx = 0
                                while True:
                                    try:
                                        v_name, v_val, v_type = winreg.EnumValue(sk, v_idx)
                                        v_idx += 1
                                    except OSError:
                                        break
                                    if v_type == winreg.REG_BINARY and isinstance(v_val, bytes) and len(v_val) >= 8:
                                        ts = filetime_bytes_to_epoch(v_val[:8])
                                        if ts > 0.0:
                                            _record_usage_key(usage, str(v_name), ts)
                        except OSError:
                            continue
            except OSError:
                continue
    except Exception:
        pass

    # 2.5 Windows Explorer UserAssist (HKCU - fully readable without UAC elevation)
    try:
        ua_root = r"Software\Microsoft\Windows\CurrentVersion\Explorer\UserAssist"
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, ua_root) as rk:
            g_idx = 0
            while True:
                try:
                    guid = winreg.EnumKey(rk, g_idx)
                    g_idx += 1
                except OSError:
                    break
                try:
                    with winreg.OpenKey(rk, rf"{guid}\Count") as ck:
                        v_idx = 0
                        while True:
                            try:
                                v_name, v_val, _v_type = winreg.EnumValue(ck, v_idx)
                                v_idx += 1
                            except OSError:
                                break
                            ts = parse_userassist_blob(v_val)
                            if ts > 0.0:
                                dec = decode_userassist_name(str(v_name))
                                if dec:
                                    _record_userassist_entry(usage, dec, ts)
                except OSError:
                    continue
    except Exception:
        pass

    # 2.6 JumplistData (HKCU, sin UAC): registra aperturas recientes que UserAssist no actualiza
    _read_jumplist_data(usage)

    # 3. Windows Prefetch (*.pf mtime reflects recent launches if readable)
    try:
        prefetch_dir = Path(os.environ.get("WINDIR", r"C:\Windows")) / "Prefetch"
        if prefetch_dir.exists():
            for entry in os.scandir(prefetch_dir):
                if entry.name.lower().endswith(".pf"):
                    app_part = entry.name.rsplit("-", 1)[0].lower()
                    try:
                        st = entry.stat()
                        _record_usage_key(usage, app_part, float(st.st_mtime))
                    except OSError:
                        continue
    except OSError:
        pass

    return usage


def _extract_exe_candidates(command: str) -> list[str]:
    clean = (command or "").strip().strip('"').strip("'")
    if not clean or ".exe" not in clean.lower():
        return []
    m = re.search(r'([A-Za-z]:[^"\r\n*?<>|]*?\.exe|[^\\/\s"\'\r\n]+?\.exe)', clean, re.IGNORECASE)
    if not m:
        return []
    exe_token = m.group(1).replace("/", "\\").strip()
    base = exe_token.rsplit("\\", 1)[-1].lower()
    if not base or base in ("uninstall.exe", "unins000.exe", "uninst.exe", "setup.exe", "msiexec.exe"):
        return []
    stem = base[:-4] if base.endswith(".exe") else base
    out = [base, stem]
    norm = _norm_alnum(stem)
    if len(norm) >= 4:
        out.append(f"{_NORM_PREFIX}{norm}")
    return out


def _clean_app_display_name(name: str) -> str:
    clean = (name or "").strip().lower()
    if not clean:
        return ""
    clean = re.sub(r"[®™©]", " ", clean)
    clean = re.sub(r"\([^)]*\)", " ", clean)
    clean = re.sub(r"\bv?\d+(?:\.\d+){1,4}\b", " ", clean)
    return re.sub(r"\s+", " ", clean).strip(" -_")


def lookup_usage_ts(
    usage_map: dict[str, float],
    *,
    name: str = "",
    command: str = "",
    install_dir: str = "",
) -> float:
    """Resolve real execution timestamp for an app/startup item without vendor false-positives."""
    best = 0.0
    candidates = _extract_exe_candidates(command)

    if name:
        nlow = name.strip().lower()
        clean_name = _clean_app_display_name(name)
        for nm in (nlow, clean_name):
            if not nm:
                continue
            candidates.extend([nm, f"{nm}.exe"])
            norm = _norm_alnum(nm)
            if len(norm) >= 4:
                candidates.append(f"{_NORM_PREFIX}{norm}")

        # Strip generic trailing role word ('Antigravity IDE' -> 'antigravity')
        words = [w for w in clean_name.split() if w]
        if len(words) == 2 and words[1] in _GENERIC_APP_TOKENS and words[0] not in _GENERIC_APP_TOKENS:
            w0_norm = _norm_alnum(words[0])
            if len(w0_norm) >= 4:
                candidates.append(f"{_NORM_PREFIX}{w0_norm}")
                candidates.extend([words[0], f"{words[0]}.exe"])
        if len(words) >= 2 and words[0] in ("microsoft", "google", "adobe"):
            tail_name = " ".join(words[1:])
            tail_norm = _norm_alnum(tail_name)
            if len(tail_norm) >= 6:
                candidates.extend([tail_name, f"{_NORM_PREFIX}{tail_norm}"])

        clean_low = clean_name or nlow
        is_component = any(t in clean_low for t in _COMPONENT_MARKERS)
        for needle, exes in _SUITE_ALIASES:
            if needle in clean_low and not is_component:
                for exe in exes:
                    candidates.extend([exe, f"{exe}.exe", f"{_NORM_PREFIX}{_norm_alnum(exe)}"])

    for cand in candidates:
        ts = usage_map.get(cand, 0.0)
        if ts > best:
            best = ts

    # Full install_dir path match inside BAM (\Device\HarddiskVolume*\...) or expanded UserAssist paths
    norm_dir = install_dir.strip().strip('"').strip("'").replace("/", "\\").lower().rstrip("\\")
    if best == 0.0 and norm_dir and norm_dir not in _BROAD_INSTALL_DIRS and norm_dir.count("\\") >= 2:
        dir_prefix = norm_dir + "\\"
        tail_dir = norm_dir[2:] + "\\" if len(norm_dir) >= 3 and norm_dir[1] == ":" else ""
        for key, ts in usage_map.items():
            if key.startswith(_NORM_PREFIX) or "\\" not in key:
                continue
            if key.startswith(dir_prefix) or (tail_dir and tail_dir in key):
                base = key.rsplit("\\", 1)[-1]
                if base in ("uninstall.exe", "unins000.exe", "uninst.exe", "setup.exe"):
                    continue
                if ts > best:
                    best = ts
    return best


def get_running_ram_by_exe() -> dict[str, float]:
    """Return aggregate RSS RAM (MB) keyed by lowercase process executable name."""
    totals: dict[str, float] = {}
    try:
        for proc in psutil.process_iter(attrs=["name", "memory_info"]):
            info = proc.info
            nm = str(info.get("name") or "").lower()
            mem = info.get("memory_info")
            if nm and mem is not None:
                rss_mb = float(getattr(mem, "rss", 0)) / (1024 * 1024)
                totals[nm] = totals.get(nm, 0.0) + rss_mb
                totals[nm.removesuffix(".exe")] = totals.get(nm.removesuffix(".exe"), 0.0) + rss_mb
    except Exception:
        pass
    return totals
