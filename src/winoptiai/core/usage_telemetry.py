"""Shared last-used timestamp formatting and Windows application usage telemetry (BAM / Prefetch / live processes)."""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import time
import psutil

from .win32_bridge import IS_WINDOWS

_EPOCH_DIFF_1601_1970 = 116_444_736_000_000_000  # 100-ns intervals between 1601-01-01 and 1970-01-01


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


def _record_usage_key(usage: dict[str, float], name_or_path: str, ts: float) -> None:
    if ts <= 0.0 or not name_or_path:
        return
    clean = name_or_path.replace("/", "\\").strip().lower()
    if not clean:
        return
    base = clean.rsplit("\\", 1)[-1]
    stem = base[:-4] if base.endswith(".exe") else base
    for key in (clean, base, stem):
        if key and ts > usage.get(key, 0.0):
            usage[key] = ts


def read_windows_app_usage_map() -> dict[str, float]:
    """Read last-executed timestamps by exe/path from Windows BAM, Prefetch, and active processes."""
    usage: dict[str, float] = {}
    now = time.time()

    # 1. Live processes right now
    try:
        for proc in psutil.process_iter(attrs=["name", "exe", "create_time"]):
            info = proc.info
            ct = float(info.get("create_time") or now)
            ts = max(now, ct)
            if info.get("name"):
                _record_usage_key(usage, str(info["name"]), ts)
            if info.get("exe"):
                _record_usage_key(usage, str(info["exe"]), ts)
    except Exception:
        pass

    if not IS_WINDOWS:
        return usage

    # 2. Windows Background Activity Moderator (BAM) registry timestamps
    try:
        import winreg

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


def lookup_usage_ts(
    usage_map: dict[str, float],
    *,
    name: str = "",
    command: str = "",
    install_dir: str = "",
) -> float:
    """Resolve best matching execution/last-used timestamp for an app or startup entry."""
    best = 0.0
    candidates: list[str] = []
    if command:
        cmd_clean = command.strip().strip('"').strip("'")
        exe_token = cmd_clean.split(" -")[0].split(" /")[0].strip('"')
        if ".exe" in exe_token.lower():
            idx = exe_token.lower().find(".exe") + 4
            exe_token = exe_token[:idx].strip('"').strip()
        if exe_token:
            base = exe_token.replace("/", "\\").rsplit("\\", 1)[-1].lower()
            candidates.extend([base, base.removesuffix(".exe")])
    if name:
        nlow = name.strip().lower()
        candidates.extend([nlow, f"{nlow}.exe", nlow.split(" ")[0]])

    for cand in candidates:
        ts = usage_map.get(cand, 0.0)
        if ts > best:
            best = ts

    # Match against exe name or install folder inside BAM full paths
    if best == 0.0 and (install_dir or candidates):
        norm_dir = install_dir.replace("/", "\\").lower().rstrip("\\")
        for key, ts in usage_map.items():
            if norm_dir and len(norm_dir) >= 8 and norm_dir in key and ts > best:
                best = ts
                continue
            for cand in candidates:
                if len(cand) >= 4 and (key == cand or key.endswith("\\" + cand)):
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
