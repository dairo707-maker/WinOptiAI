"""v0.6.3: ULTIMO USO preciso, actualizar apps en lote y Vigia diario."""

from __future__ import annotations

from datetime import datetime
import struct
import time

from winoptiai.apps.app_manager import InstalledApp, bulk_upgrade_skip_reason, upgrade_apps_winget
from winoptiai.core import daily_watch
from winoptiai.core.task_control import TaskController
from winoptiai.core.usage_telemetry import (
    _record_userassist_entry,
    lookup_usage_ts,
    resolve_lnk_target,
    visible_window_pids,
)


def test_browser_profiles_count_as_browser_and_webview_is_ignored():
    usage: dict[str, float] = {}
    now = time.time()
    _record_userassist_entry(usage, "Chrome.UserData.Profile2", now - 100)
    _record_userassist_entry(usage, "Chrome.cdpFdi6oa.Default", now - 5000)
    _record_userassist_entry(usage, "MSEdgeWebView.EBWebView.Default", now - 10)
    assert abs(lookup_usage_ts(usage, name="Google Chrome") - (now - 100)) < 1.0
    # WebView2 lo abren otras apps: no es uso de Edge
    assert lookup_usage_ts(usage, name="Microsoft Edge") == 0.0
    # Los perfiles no dejan claves basura como 'default' o 'profile2'
    assert "__norm:default" not in usage and "__norm:profile2" not in usage


def test_office_suite_alias_and_components_do_not_inherit():
    usage: dict[str, float] = {}
    now = time.time()
    _record_userassist_entry(usage, "Microsoft.Office.EXCEL.EXE.15", now - 3600)
    _record_userassist_entry(usage, "Microsoft.Office.WINWORD.EXE.15", now - 7200)
    assert abs(lookup_usage_ts(usage, name="Aplicaciones de Microsoft 365 para negocios - es-es") - (now - 3600)) < 1.0
    assert lookup_usage_ts(usage, name="Microsoft Teams Meeting Add-in for Microsoft Office") == 0.0


def test_stata_and_zoom_aliases():
    usage: dict[str, float] = {}
    now = time.time()
    _record_userassist_entry(usage, "zoom.us.Zoom Video Meetings", now - 86400)
    assert abs(lookup_usage_ts(usage, name="Zoom Workplace") - (now - 86400)) < 1.0


def _build_ansi_lnk(target: str) -> bytes:
    header = bytearray(76)
    struct.pack_into("<I", header, 0, 0x4C)
    struct.pack_into("<I", header, 20, 0x2)  # HasLinkInfo
    base = target.encode("latin-1") + b"\x00"
    li_header = 0x1C
    local_off = li_header
    suffix_off = local_off + len(base)
    size = suffix_off + 1
    linkinfo = struct.pack("<IIIIIII", size, li_header, 0x1, 0, local_off, 0, suffix_off) + base + b"\x00"
    return bytes(header) + linkinfo


def test_resolve_lnk_target_reads_local_base_path(tmp_path):
    lnk = tmp_path / "StataMP 17 (64-bit).lnk"
    lnk.write_bytes(_build_ansi_lnk(r"C:\Program Files\Stata17\StataMP-64.exe"))
    assert resolve_lnk_target(str(lnk)) == r"C:\Program Files\Stata17\StataMP-64.exe"
    assert resolve_lnk_target(str(tmp_path / "no_existe.lnk")) == ""


def test_lnk_usage_records_target_exe(tmp_path):
    lnk = tmp_path / "Mi Programa.lnk"
    lnk.write_bytes(_build_ansi_lnk(r"C:\Apps\MiProg\miprog.exe"))
    usage: dict[str, float] = {}
    now = time.time()
    _record_userassist_entry(usage, str(lnk), now - 50)
    assert abs(usage.get("miprog.exe", 0.0) - (now - 50)) < 1.0


def test_visible_window_pids_returns_set():
    assert isinstance(visible_window_pids(), set)


def _app(name, ver, new, wid="", prot=""):
    return InstalledApp(app_id=name, name=name, version=ver, available_version=new, winget_id=wid, protected_reason=prot)


def test_bulk_upgrade_skip_reason_rules():
    assert bulk_upgrade_skip_reason(_app("Notepad++ (64-bit x64)", "8.8.8", "8.9.9.1")) == ""
    assert "mayor" in bulk_upgrade_skip_reason(_app("Zotero", "7.0.9", "10.0.8"))
    assert "desarrollo" in bulk_upgrade_skip_reason(_app("Python 3.13.13 (64-bit)", "3.13.13", "3.13.17"))
    assert "desarrollo" in bulk_upgrade_skip_reason(_app("Anaconda3 2021.11", "2021.11", "2021.12"))
    assert bulk_upgrade_skip_reason(_app("X", "1.0", "1.1", prot="Componente critico")) == "Componente critico"
    assert bulk_upgrade_skip_reason(_app("Y", "1.0", "")) == "Sin nueva version"


def test_upgrade_apps_winget_sequential_and_cancellable():
    apps = [_app(f"App{i}", "1.0", "1.1") for i in range(4)]
    calls: list[str] = []
    ctl = TaskController("t")

    def fake(app):
        calls.append(app.name)
        if len(calls) == 2:
            ctl.cancel()
        return True, f"{app.name} ok"

    res = upgrade_apps_winget(apps, controller=ctl, upgrade_fn=fake)
    assert calls == ["App0", "App1"]
    assert [a.version for a, _ok, _m in res] == ["1.1", "1.1"]
    assert apps[2].available_version == "1.1"  # no se intento


def test_daily_watch_due_slot():
    hours = [9, 14, 19]
    assert daily_watch.due_slot(datetime(2026, 11, 21, 8, 59), hours, "") is None
    assert daily_watch.due_slot(datetime(2026, 11, 21, 9, 5), hours, "") == "2026-11-21@09"
    assert daily_watch.due_slot(datetime(2026, 11, 21, 10, 0), hours, "2026-11-21@09") is None
    # Equipo suspendido de 12 a 20: un solo aviso por el horario mas reciente
    assert daily_watch.due_slot(datetime(2026, 11, 21, 20, 30), hours, "2026-11-21@09") == "2026-11-21@19"
    assert daily_watch.sanitize_hours(["x", 25, True]) == [9, 14, 19]
    assert daily_watch.sanitize_hours([20, 8, 8]) == [8, 20]


def test_daily_watch_digest_and_repeat_rules():
    f = daily_watch.WatchFindings(app_updates=["Notepad++", "WinRAR"], manual_updates=3, junk_bytes=800 * 1024**2, junk_files=120)
    items = daily_watch.build_digest(f)
    assert [it["key"] for it in items] == ["updates", "junk"]
    assert items[0]["action_tab"] == daily_watch.TAB_APPS
    assert "3" in items[0]["detail"]
    assert daily_watch.build_digest(daily_watch.WatchFindings(junk_bytes=10 * 1024**2)) == []
    sig = daily_watch.digest_signature(items)
    now = time.time()
    assert daily_watch.should_send(sig, "", 0.0, now)
    assert not daily_watch.should_send(sig, sig, now - 3600, now)
    assert daily_watch.should_send(sig, sig, now - 21 * 3600, now)
    assert not daily_watch.should_send("", "", 0.0, now)
