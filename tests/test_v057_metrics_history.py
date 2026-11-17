"""WinOptiAI v0.5.7: historial de metricas, graficos QPainter, eventos de auditoria e instancia unica."""

from __future__ import annotations

from datetime import datetime, timedelta
import json
import os
from pathlib import Path
import sys
import time
import uuid

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPixmap  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from winoptiai.core.metrics_history import (  # noqa: E402
    EVENT_BOOST,
    EVENT_CLEAN,
    EVENT_ERROR,
    EVENT_PURGE,
    FREED_DUPS,
    FREED_ONEDRIVE,
    FREED_QUARANTINE,
    FREED_TEMP,
    RANGE_24H,
    RANGE_7D,
    RETENTION_SECONDS,
    MetricSample,
    MetricsHistory,
    MetricsStore,
    MinuteAggregator,
    classify_event,
    freed_totals_by_kind,
    load_audit_events,
)
from winoptiai.core.single_instance import SingleInstanceLock  # noqa: E402
from winoptiai.core.sre_policy import SREPolicyEngine  # noqa: E402
from winoptiai.ui.theme import build_obsidian_qss, get_palette, register_embedded_fonts  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    register_embedded_fonts(app)
    return app


def _pump_until(app: QApplication, cond, timeout: float = 5.0) -> bool:
    end = time.time() + timeout
    while time.time() < end:
        app.processEvents()
        if cond():
            return True
        time.sleep(0.02)
    return cond()


def _sample(ts: float, ram: float = 3.0, cpu: float = 20.0) -> MetricSample:
    return MetricSample(int(ts), ram, 16.0, cpu, 55.0, 100.0, 200.0)


def _audit_line(ts: datetime, actor: str, action: str, detail: str, mb: float) -> str:
    return json.dumps({"timestamp": ts.astimezone().isoformat(), "actor": actor, "action": action, "detail": detail, "freed_mb": mb}) + "\n"


# --------------------------------------------------------------------------- almacen
def test_store_keeps_only_seven_days(tmp_path: Path) -> None:
    store = MetricsStore(tmp_path / "metrics.sqlite")
    now = time.time()
    store.add(_sample(now - RETENTION_SECONDS - 3600), now=now)
    store.add(_sample(now - 3600), now=now)
    store.add(_sample(now - 60), now=now)
    assert store.count() == 2  # la muestra de hace mas de 7 dias se purgo al insertar


def test_store_query_downsamples_to_max_points(tmp_path: Path) -> None:
    store = MetricsStore(tmp_path / "metrics.sqlite")
    now = time.time()
    for i in range(1, 24 * 60 + 1):  # 1 punto por minuto durante 24 h
        store.add(_sample(now - i * 60, ram=2.0 + (i % 2), cpu=50.0), now=now)
    full = store.query(RANGE_24H, now=now, max_points=10_000)
    assert 1400 <= len(full) <= 1441
    small = store.query(RANGE_24H, now=now, max_points=100)
    assert len(small) <= 101
    assert all(2.0 <= s.ram_free_gb <= 3.0 for s in small)  # promedios por cubeta
    assert small == sorted(small, key=lambda s: s.ts)


def test_minute_aggregator_averages_and_emits_once_per_minute() -> None:
    agg = MinuteAggregator(interval=60)
    t0 = 1_000_000.0
    assert agg.add(2.0, 16.0, 10.0, None, now=t0) is None
    assert agg.add(4.0, 16.0, 30.0, 60.0, now=t0 + 30) is None
    out = agg.add(3.0, 16.0, 20.0, 62.0, now=t0 + 60)
    assert out is not None
    assert out["ram_free_gb"] == pytest.approx(3.0)
    assert out["cpu_pct"] == pytest.approx(20.0)
    assert out["cpu_temp_c"] == pytest.approx(61.0)
    assert agg.add(3.0, 16.0, 20.0, None, now=t0 + 70) is None  # vuelve a empezar


def test_history_records_off_thread_and_builds_snapshot(tmp_path: Path) -> None:
    hist = MetricsHistory(tmp_path)
    try:
        now = time.time()
        sample = hist.record_async({"ts": now, "ram_free_gb": 2.5, "ram_total_gb": 16.0, "cpu_pct": 40.0, "cpu_temp_c": None}).result(5)
        assert sample.disk_free_gb is None or sample.disk_free_gb > 0
        assert sample.app_ram_mb is None or sample.app_ram_mb > 0
        snap = hist.submit(hist.load_snapshot, RANGE_24H).result(5)
        assert len(snap["samples"]) == 1 and snap["events"] == []
    finally:
        hist.shutdown()


# --------------------------------------------------------------------------- auditoria
def test_classify_events_and_freed_totals(tmp_path: Path) -> None:
    assert classify_event("sre_auto", "AI Boost") == EVENT_BOOST
    assert classify_event("usuario", "Limpieza temporales") == EVENT_CLEAN
    assert classify_event("usuario", "Depuracion cuarentena") == EVENT_PURGE
    assert classify_event("crash_guard", "Informe de error") == EVENT_ERROR
    assert classify_event("usuario", "Perfil termico") is None

    now = datetime.now()
    audit = tmp_path / "audit.jsonl"
    audit.write_text(
        _audit_line(now - timedelta(hours=5), "sre_auto", "AI Boost", "RAM", 215.0)
        + _audit_line(now - timedelta(hours=4), "usuario", "Limpieza temporales", "t", 100.0)
        + _audit_line(now - timedelta(hours=3), "usuario", "Hardlink NTFS", "h", 50.0)
        + _audit_line(now - timedelta(hours=2), "usuario", "Depuracion cuarentena", "q", 300.0)
        + _audit_line(now - timedelta(hours=1), "usuario", "OneDrive Nube Papelera", "o", 38.7)
        + "linea corrupta\n",
        encoding="utf-8",
    )
    events = load_audit_events(audit)
    assert len(events) == 5
    totals = freed_totals_by_kind(events)
    # AI Boost libera RAM, no disco: no se suma al espacio liberado.
    assert totals == {FREED_TEMP: 100.0, FREED_DUPS: 50.0, FREED_QUARANTINE: 300.0, FREED_ONEDRIVE: 38.7}


def test_load_audit_events_ignores_exact_duplicates(tmp_path: Path) -> None:
    ts = datetime.now() - timedelta(minutes=5)
    line = _audit_line(ts, "sre_auto", "AI Boost", "RAM libre: 0.84 -> 1.05 GB", 215.0)
    audit = tmp_path / "audit.jsonl"
    audit.write_text(line + line, encoding="utf-8")  # caso real del 16/11 22:45:35
    assert len(load_audit_events(audit)) == 1


def test_record_audit_event_skips_immediate_duplicate(tmp_path: Path) -> None:
    pol = SREPolicyEngine(app_dir=tmp_path)
    pol.record_audit_event("sre_auto", "AI Boost", "RAM libre: 0.84 -> 1.05 GB", 215.0)
    pol.record_audit_event("sre_auto", "AI Boost", "RAM libre: 0.84 -> 1.05 GB", 215.0)
    pol.record_audit_event("sre_auto", "AI Boost", "RAM libre: 1.00 -> 1.20 GB", 200.0)
    lines = pol.audit_path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2

    # Un evento identico fuera de la ventana (otro AI Boost real minutos despues) si se registra.
    old = datetime.now() - timedelta(minutes=5)
    pol.audit_path.write_text(_audit_line(old, "usuario", "AI Boost", "x", 1.0), encoding="utf-8")
    pol.record_audit_event("usuario", "AI Boost", "x", 1.0)
    assert len(pol.audit_path.read_text(encoding="utf-8").splitlines()) == 2


# --------------------------------------------------------------------------- instancia unica
@pytest.mark.skipif(sys.platform != "win32", reason="mutex con nombre de Windows")
def test_single_instance_lock_blocks_second_instance() -> None:
    key = f"WinOptiAI-test-{uuid.uuid4().hex[:8]}"
    first = SingleInstanceLock(key)
    assert first.acquire()
    import threading

    result: dict[str, bool] = {}

    def _other_thread() -> None:  # el mutex es por hilo: probar desde otro hilo = otro dueno
        second = SingleInstanceLock(key)
        result["busy"] = second.acquire(wait_ms=0)
        second.release()
        first_released.wait(5)
        third = SingleInstanceLock(key)
        result["after"] = third.acquire(wait_ms=2000)
        third.release()

    first_released = threading.Event()
    t = threading.Thread(target=_other_thread)
    t.start()
    time.sleep(0.3)
    first.release()
    first_released.set()
    t.join(10)
    assert result == {"busy": False, "after": True}


def test_elevated_relaunch_passes_wait_argument() -> None:
    from winoptiai.ui import main_window

    src = Path(main_window.__file__).read_text(encoding="utf-8")
    assert "ELEVATED_RELAUNCH_ARG" in src and "--elevated-relaunch" in src
    app_src = (Path(main_window.__file__).parents[1] / "app.py").read_text(encoding="utf-8")
    assert "SingleInstanceLock" in app_src and "_notify_running_instance" in app_src


# --------------------------------------------------------------------------- graficos
def test_time_series_chart_paints_series_threshold_and_markers(qapp: QApplication) -> None:
    from winoptiai.core.metrics_history import AuditEvent
    from winoptiai.ui.history_charts import TimeSeriesChart

    chart = TimeSeriesChart(lambda: get_palette("dark"))
    chart.resize(700, 240)
    now = time.time()
    samples = [_sample(now - i * 120, ram=1.0 + (i % 5), cpu=float(i % 100)) for i in range(700, 0, -1)]
    samples.insert(200, _sample(now - 3600 * 30))  # fuera de rango: se recorta al borde
    events = [
        AuditEvent(now - 3600, "sre_auto", "AI Boost", "RAM", 215.0, EVENT_BOOST, None),
        AuditEvent(now - 7200, "crash_guard", "Informe de error", "E", 0.0, EVENT_ERROR, None),
    ]
    chart.set_data(sorted(samples, key=lambda s: s.ts), events, now, RANGE_24H, 1.8)
    pm = QPixmap(chart.size())
    chart.render(pm)
    assert len(chart._event_hits) == 2
    assert chart.ram_scale_max() >= 5.0
    ram, cpu, strip = chart.bands()
    assert ram.bottom() < cpu.top() < cpu.bottom() < strip.bottom()
    assert chart.x_for(now) == pytest.approx(ram.right())
    assert chart.nearest_sample(chart.x_for(samples[-1].ts)) is not None


def test_time_series_chart_breaks_line_on_gaps(qapp: QApplication) -> None:
    from winoptiai.ui.history_charts import TimeSeriesChart

    chart = TimeSeriesChart(lambda: get_palette("light"))
    now = time.time()
    a = [_sample(now - 7200 + i * 60) for i in range(10)]
    b = [_sample(now - 600 + i * 60) for i in range(5)]  # la app estuvo cerrada ~1.5 h
    chart.set_data(a + b, [], now, RANGE_24H, 1.8)
    assert [len(s) for s in chart._segments()] == [10, 5]


def test_freed_chart_stacks_cumulative_totals(qapp: QApplication) -> None:
    from winoptiai.core.metrics_history import AuditEvent
    from winoptiai.ui.history_charts import FreedSpaceChart

    now = time.time()
    events = [
        AuditEvent(now - 300, "u", "Limpieza temporales", "", 100.0, EVENT_CLEAN, FREED_TEMP),
        AuditEvent(now - 200, "u", "Duplicados BLAKE3", "", 50.0, EVENT_CLEAN, FREED_DUPS),
        AuditEvent(now - 100, "u", "Limpieza temporales", "", 25.0, EVENT_CLEAN, FREED_TEMP),
        AuditEvent(now - 50, "sre_auto", "AI Boost", "", 999.0, EVENT_BOOST, None),  # RAM: excluido
    ]
    chart = FreedSpaceChart(lambda: get_palette("dark"))
    chart.resize(600, 200)
    chart.set_data(events, now)
    pts = chart.stacked_totals()
    assert [sum(v.values()) for _, v in pts] == [100.0, 150.0, 175.0]
    assert pts[-1][1][FREED_TEMP] == 125.0
    chart.render(QPixmap(chart.size()))


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_overview_history_panel_loads_async_without_clipping(qapp: QApplication, tmp_path: Path, monkeypatch, mode: str) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    app_dir = tmp_path / "WinOptiAI"
    app_dir.mkdir(parents=True)
    now = time.time()
    store = MetricsStore(app_dir / "metrics.sqlite")
    for i in range(1, 300):
        store.add(_sample(now - i * 60, ram=2.0 + (i % 3)), now=now)
    (app_dir / "audit.jsonl").write_text(
        _audit_line(datetime.now() - timedelta(hours=1), "sre_auto", "AI Boost", "RAM", 200.0)
        + _audit_line(datetime.now() - timedelta(minutes=30), "usuario", "Limpieza temporales", "t", 512.0),
        encoding="utf-8",
    )
    from winoptiai.ui.main_window import MainWindow
    from winoptiai.ui.widgets import find_clipped_buttons

    win = MainWindow()
    try:
        win.policy.config.auto_ram_relief_enabled = False
        win.policy.config.theme_mode = mode
        qapp.setStyleSheet(build_obsidian_qss(mode))
        win._apply_ui_appearance()
        win.resize(980, 650)
        win.show()
        ov = win.overview_view
        ov.schedule_history_refresh(0)
        assert _pump_until(qapp, lambda: len(ov.history_panel.chart.samples) > 100)  # 300 min en cubetas de 2 min
        assert any(e.category == EVENT_BOOST for e in ov.history_panel.chart.events)
        assert "AI Boost" in ov.history_panel.summary_lbl.text()
        ov.monitor_tabs.setCurrentWidget(ov.freed_panel)
        assert _pump_until(qapp, lambda: ov.freed_panel.legend.totals[FREED_TEMP] == 512.0)
        assert ov.history_panel.chart.height() >= 150
        for idx in range(3):
            ov.monitor_tabs.setCurrentIndex(idx)
            qapp.processEvents()
            assert find_clipped_buttons(win) == []
        ov.history_panel.set_range(RANGE_7D)
        assert _pump_until(qapp, lambda: ov.history_panel.chart.range_s == RANGE_7D)
    finally:
        win._force_quit = True
        win.close()


def test_second_instance_brings_existing_window_to_front(qapp: QApplication) -> None:
    import threading

    from winoptiai.app import _notify_running_instance, _start_activation_server

    key = f"WinOptiAI-test-{uuid.uuid4().hex[:8]}"
    calls: list[int] = []
    server = _start_activation_server(key, lambda: calls.append(1))
    try:
        assert server.isListening()
        t = threading.Thread(target=_notify_running_instance, args=(key,))
        t.start()
        assert _pump_until(qapp, lambda: bool(calls), timeout=5.0)
        t.join(5)
    finally:
        server.close()
