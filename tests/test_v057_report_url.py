"""WinOptiAI v0.5.7: el informe a GitHub nunca supera el limite que provoca "Whoops" (HTTP 500)."""

from __future__ import annotations

from pathlib import Path
from urllib.parse import parse_qs, urlparse

from winoptiai.core import crash_reporter as cr
from winoptiai.core.crash_guard import CrashGuard


def _big_guard(tmp_path: Path) -> CrashGuard:
    g = CrashGuard(app_dir=tmp_path, version="0.5.7")
    g.begin_session()
    tb = "Traceback (most recent call last):\r\n" + '  File "winoptiai\\ui\\main_window.py", line 700, in x\r\n' * 80
    g.write_log_block("EXCEPCION NO CONTROLADA", tb)
    return g


def test_issue_url_stays_below_signed_out_github_limit(tmp_path: Path) -> None:
    g = _big_guard(tmp_path)
    body = cr.build_report_markdown(g, cr.KIND_ERROR, "ValueError: x")
    assert "\r" not in body
    url, truncated = cr.build_issue_url(cr.build_issue_title(g, cr.KIND_ERROR, "ValueError"), body)
    # Sin sesion GitHub redirige a /login?return_to=<url codificada de nuevo>; 3.000 deja margen
    # frente a los ~5.900 que dieron HTTP 500 el 17/11/2026.
    assert truncated and len(url) <= 3000 == cr.MAX_ISSUE_URL_CHARS
    sent = parse_qs(urlparse(url).query)["body"][0]
    assert sent.startswith("### Resumen") and sent.count("```") % 2 == 0  # bloques cerrados
    assert "Ctrl+V" in sent and "reports" in sent


def test_save_pause_only_offered_for_resumable_tasks(tmp_path: Path, monkeypatch) -> None:
    import os
    import threading

    os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from winoptiai.ui import main_window as mw

    win = mw.MainWindow()
    gate = threading.Event()
    try:
        monkeypatch.setattr(win.pool, "start", lambda _w: None)  # no ejecutar: solo ver la barra
        win._run_async(lambda: gate.wait(1), lambda _r: None, "Arbol almacenamiento")
        assert win.pause_top_btn.isVisibleTo(win) and not win.save_pause_top_btn.isVisibleTo(win)
        win._active_workers.clear()
        win._run_async(lambda: gate.wait(1), lambda _r: None, "Limpieza temporales", supports_save=True)
        assert win.save_pause_top_btn.isVisibleTo(win)
    finally:
        gate.set()
        win._active_workers.clear()
        win.heartbeat_timer.stop()
        win.telemetry_timer.stop()
        win.deleteLater()
        app.processEvents()


def test_full_report_saved_to_local_file(tmp_path: Path) -> None:
    text = "### Resumen\ninforme completo"
    path = cr.save_report_file(text, tmp_path)
    assert path is not None and path.parent == tmp_path / "reports"
    assert path.read_text(encoding="utf-8") == text
