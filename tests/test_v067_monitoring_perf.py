"""Tests for WinOptiAI v0.6.7: Extended PDH telemetry, bottleneck diagnosis, Focus Mode, Standby, Scheduled Tasks & Services."""

from __future__ import annotations

import os
from pathlib import Path
import sqlite3
import subprocess
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication, QScrollArea  # noqa: E402

from winoptiai.ai_optimizer.process_manager import (  # noqa: E402
    FocusModeManager,
    apply_manual_process_ecoqos,
    apply_manual_process_io_priority,
    list_top_processes,
)
from winoptiai.apps.startup_manager import (  # noqa: E402
    StartupItem,
    classify_third_party_services,
    parse_schtasks_logon_csv,
    read_last_boot_summary,
    set_startup_item_enabled,
)
from winoptiai.core.metrics_history import (  # noqa: E402
    MetricSample,
    MetricsStore,
    MinuteAggregator,
    RANGE_24H,
)
from winoptiai.core.safety_guard import PreOpBackupManager  # noqa: E402
from winoptiai.core.telemetry import (  # noqa: E402
    LiveSystemTelemetry,
    PdhTelemetryReader,
    SustainedBottleneckMonitor,
    diagnose_bottleneck,
    read_performance_info,
)
from winoptiai.core.win32_bridge import (  # noqa: E402
    purge_standby_memory_list,
    set_focus_keep_awake,
    set_process_io_priority,
)
from winoptiai.ui.history_charts import HistoryPanel  # noqa: E402
from winoptiai.ui.main_window import MainWindow  # noqa: E402
from winoptiai.ui.theme import build_obsidian_qss, get_palette, register_embedded_fonts  # noqa: E402
from winoptiai.ui.widgets import find_clipped_buttons  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    register_embedded_fonts(app)
    return app


def _pump(app: QApplication, n: int = 8) -> None:
    for _ in range(n):
        app.processEvents()


def test_extended_telemetry_perf_info_and_bottleneck_diagnosis() -> None:
    pinfo = read_performance_info()
    assert pinfo["commit_limit_gb"] > 0.5
    assert pinfo["commit_used_gb"] > 0.1
    assert pinfo["handles"] > 100
    assert pinfo["threads"] > 10

    reader = PdhTelemetryReader(lazy_init=False)
    time.sleep(0.25)
    sample = reader.sample()
    assert sample.commit_limit_gb > 0.5
    assert sample.handles_count > 100
    assert sample.disk_active_pct >= 0.0
    assert sample.net_rx_mb_s >= 0.0

    # Priority ordering of bottleneck rules + sustained alert window
    thermal = LiveSystemTelemetry(30.0, 2000.0, 100.0, [30.0], 90.0, None, "OK")
    d_therm = diagnose_bottleneck(thermal, 40.0, 8.0, 2.0)
    assert d_therm.code == "thermal" and d_therm.tone == "risk"

    disk_sat = LiveSystemTelemetry(25.0, 2200.0, 100.0, [25.0], 55.0, None, "OK", disk_active_pct=96.0, disk_queue_len=5.2)
    d_disk = diagnose_bottleneck(disk_sat, 40.0, 8.0, 2.0)
    assert d_disk.code == "disk_io" and d_disk.tone == "risk"

    mem_crunch = LiveSystemTelemetry(20.0, 2000.0, 100.0, [20.0], 55.0, None, "OK", commit_pct=94.0)
    d_mem = diagnose_bottleneck(mem_crunch, 88.0, 1.5, 2.0)
    assert d_mem.code == "memory_commit" and d_mem.tone == "risk"

    ok_live = LiveSystemTelemetry(18.0, 1800.0, 90.0, [18.0], 52.0, None, "OK", commit_pct=45.0, disk_active_pct=10.0)
    d_ok = diagnose_bottleneck(ok_live, 42.0, 9.0, 2.0)
    assert d_ok.code == "balanced" and d_ok.tone == "ok"

    mon = SustainedBottleneckMonitor(sustain_seconds=30.0, cooldown_seconds=600.0)
    assert mon.feed(d_disk, now=100.0) is None
    assert mon.feed(d_disk, now=120.0) is None
    # Brief recovery resets timer
    assert mon.feed(d_ok, now=125.0) is None
    assert mon.feed(d_disk, now=130.0) is None
    assert mon.feed(d_disk, now=161.0) is not None
    # Cooldown suppresses duplicates
    assert mon.feed(d_disk, now=200.0) is None
    assert mon.feed(d_disk, now=800.0) is not None


def test_metrics_store_migrates_legacy_db_and_aggregates_io(tmp_path: Path, qapp: QApplication) -> None:
    db_file = tmp_path / "metrics.sqlite"
    with sqlite3.connect(str(db_file)) as con:
        con.execute(
            "CREATE TABLE samples ("
            " ts INTEGER PRIMARY KEY, ram_free_gb REAL NOT NULL, ram_total_gb REAL NOT NULL,"
            " cpu_pct REAL NOT NULL, cpu_temp_c REAL, disk_free_gb REAL, app_ram_mb REAL)"
        )
        con.execute("INSERT INTO samples VALUES (1000, 6.0, 16.0, 22.0, 58.0, 120.0, 110.0)")

    store = MetricsStore(db_file)
    now = 2000.0
    store.add(MetricSample(1900, 5.5, 16.0, 35.0, 61.0, 119.5, 115.0, disk_active_pct=42.0, commit_pct=68.0, gpu_vram_mb=512.0, net_kbps=320.0), now=now)
    rows = store.query(RANGE_24H, now=now)
    assert len(rows) == 2
    assert rows[0].ts == 1000 and rows[0].disk_active_pct is None
    assert rows[1].disk_active_pct == pytest.approx(42.0)
    assert rows[1].commit_pct == pytest.approx(68.0)

    agg = MinuteAggregator(interval=60)
    assert agg.add(6.0, 16.0, 20.0, None, now=100.0, disk_active_pct=10.0, commit_pct=50.0, gpu_vram_mb=100.0, net_kbps=10.0) is None
    out = agg.add(8.0, 16.0, 40.0, 60.0, now=160.0, disk_active_pct=30.0, commit_pct=70.0, gpu_vram_mb=300.0, net_kbps=30.0)
    assert out is not None
    assert out["disk_active_pct"] == pytest.approx(20.0)
    assert out["commit_pct"] == pytest.approx(60.0)

    panel = HistoryPanel(lambda: get_palette("dark"))
    panel.resize(460, 220)
    panel.apply_snapshot({"samples": rows, "events": [], "now": now, "range": RANGE_24H})
    panel.mode_btn.click()
    assert panel.chart.secondary_mode == "io"
    pm = QPixmap(panel.chart.size())
    panel.chart.render(pm)
    assert not pm.isNull()
    panel.close()


def test_io_priority_manual_controls_standby_and_focus_mode() -> None:
    pid = os.getpid()
    assert set_process_io_priority(pid, low=True)
    assert set_process_io_priority(pid, low=False)
    assert set_focus_keep_awake(True)
    assert set_focus_keep_awake(False)

    ok_std, msg_std = purge_standby_memory_list(allow_uac=False)
    if not ok_std:
        assert "Admin" in msg_std or "UAC" in msg_std or "privilege" in msg_std.lower()

    # Guardrails protect OS, AI agents, and installers
    ok_sys, reason_sys = apply_manual_process_ecoqos(999999, "csrss.exe", True)
    assert not ok_sys and "protegido" in reason_sys.lower()
    ok_ai, reason_ai = apply_manual_process_io_priority(999999, "claude.exe", True)
    assert not ok_ai and "protegida" in reason_ai.lower()
    ok_inst, _ = apply_manual_process_ecoqos(999999, "WinOptiAI-Setup.exe", True)
    assert not ok_inst

    procs = list_top_processes(10)
    assert procs
    assert all(p.io_mb_s >= 0.0 for p in procs)

    mgr = FocusModeManager()
    info = mgr.enter(prev_thermal_profile="balanced")
    assert mgr.active and info["already_active"] is False
    rev = mgr.exit()
    assert not mgr.active
    assert rev["previous_thermal"] == "balanced"


def test_startup_tasks_services_boot_and_ui_980x650(
    qapp: QApplication, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    boot = read_last_boot_summary()
    assert boot["uptime_sec"] > 0
    assert boot["uptime_label"]

    csv_es = (
        '"Nombre de host","Nombre de tarea","Proximo tiempo de ejecucion","Estado","Modo de inicio de sesion","Ultima vez de ejecucion","Ultimo resultado","Autor","Tarea que se ejecutara","Iniciar en","Comentario","Estado de la tarea programada","Tipo de inactividad","Administracion de energia","Ejecutar como usuario","Eliminar tarea si no se vuelve a programar","Detener tarea si se ejecuta mas de X horas y X minutos","Tipo de programacion","Hora de inicio","Fecha de inicio","Fecha de fin","Dias","Meses","Repetir: cada","Repetir: hasta: duracion","Repetir: hasta: hora","Repetir: detener: si sigue ejecutando"\n'
        '"PC","\\Microsoft\\Windows\\Update\\Scan","N/D","Listo","Interactive","N/D","0","Microsoft","usoclient.exe","N/D","N/D","Habilitado","Disabled","","SYSTEM","Disabled","","Al iniciar","N/D","N/D","N/D","N/D","N/D","N/D","N/D","N/D","Disabled"\n'
        '"PC","\\MyVendor\\CloudUpdater","N/D","Listo","Interactive","N/D","0","Vendor","C:\\Tools\\updater.exe","N/D","N/D","Habilitado","Disabled","","User","Disabled","","Al iniciar sesion","N/D","N/D","N/D","N/D","N/D","N/D","N/D","N/D","Disabled"\n'
    )
    tasks = parse_schtasks_logon_csv(csv_es)
    assert len(tasks) == 1
    assert tasks[0].location_kind == "SCHTASK"
    assert tasks[0].entry_name == r"\MyVendor\CloudUpdater"

    svcs = classify_third_party_services([
        {"Name": "wuauserv", "DisplayName": "Windows Update", "PathName": r"C:\Windows\system32\svchost.exe -k netsvcs", "StartMode": "Auto"},
        {"Name": "AcmeHelper", "DisplayName": "Acme Update Service", "PathName": r'"C:\Program Files\Acme\acme.exe"', "StartMode": "Auto"},
    ])
    assert len(svcs) == 1
    assert svcs[0].location_kind == "SERVICE" and svcs[0].enabled

    bm = PreOpBackupManager(root_dir=tmp_path / "bk")
    calls: list[list[str]] = []

    class _Res:
        returncode = 0

    monkeypatch.setattr(subprocess, "run", lambda cmd, **_kw: calls.append(list(cmd)) or _Res())
    ok_t, _ = set_startup_item_enabled(tasks[0], False, backup_mgr=bm)
    assert ok_t and not tasks[0].enabled
    assert calls and "/change" in calls[0] and "/disable" in calls[0]

    # Full UI check at 980x650: zero scroll on Overview, no clipped buttons, synced Focus Mode
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    monkeypatch.setattr("winoptiai.ui.main_window.apply_thermal_profile", lambda k: (True, f"mock {k}"))
    qapp.setStyleSheet(build_obsidian_qss("dark"))
    win = MainWindow()
    try:
        win.telemetry_timer.stop()
        win._warmup_timer.stop()
        win.resize(980, 650)
        win.show()
        _pump(qapp, 10)

        assert win.overview_view.findChildren(QScrollArea) == []
        assert find_clipped_buttons(win) == []

        proc_headers = [
            win.processes_view.proc_table.horizontalHeaderItem(c).text()
            for c in range(win.processes_view.proc_table.columnCount())
        ]
        assert "E/S MB/s" in proc_headers
        assert "ULTIMO USO" in proc_headers

        for tab_idx in (1, 2, 3, 4, 5):
            win._switch_tab(tab_idx)
            _pump(qapp, 4)
            assert find_clipped_buttons(win) == [], f"Boton recortado en pestana {tab_idx}"

        win._switch_tab(0)
        _pump(qapp, 4)
        # Focus Mode toggle syncs UI + Tray cleanly and restores on disable
        win._toggle_focus_mode(True)
        assert win.focus_mgr.active
        assert win.overview_view.focus_btn.isChecked()
        assert win.processes_view.focus_btn.isChecked()
        assert win.tray.focus_action.isChecked()
        assert find_clipped_buttons(win) == []
        win._toggle_focus_mode(False)
        assert not win.focus_mgr.active
        assert not win.tray.focus_action.isChecked()
    finally:
        win._force_quit = True
        win.close()
        win.pool.waitForDone(5000)
