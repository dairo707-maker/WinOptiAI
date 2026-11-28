"""WinOptiAI v0.5.3: bloqueo en Arbol (render perezoso), vigilante de bloqueos e informe a GitHub."""

from __future__ import annotations

import os
from pathlib import Path
import threading
import time
from urllib.parse import parse_qs, urlparse

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from winoptiai.core import crash_reporter as cr  # noqa: E402
from winoptiai.core.crash_guard import CrashGuard  # noqa: E402
from winoptiai.core.safety_guard import PreOpBackupManager, QuarantineVault  # noqa: E402
from winoptiai.core.sre_policy import SREPolicyEngine  # noqa: E402
from winoptiai.storage.tree_analyzer import FolderNode, StorageHierarchyReport, analyze_storage_hierarchy  # noqa: E402
from winoptiai.ui import workers  # noqa: E402
from winoptiai.ui.dialogs.crash_send_dialog import CrashSendDialog  # noqa: E402
from winoptiai.ui.views import storage_view as sv  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    return QApplication.instance() or QApplication([])


def _view(tmp_path: Path) -> sv.StorageView:
    return sv.StorageView(
        QuarantineVault(root_dir=tmp_path),
        PreOpBackupManager(root_dir=tmp_path),
        SREPolicyEngine(app_dir=tmp_path),
        lambda *a, **k: None,
        lambda _m: None,
    )


def _wide_tree(depth: int, width: int, path: Path = Path("C:/R")) -> FolderNode:
    node = FolderNode(name=path.name, path=path, size_bytes=width**depth, file_count=1)
    if depth > 0:
        node.children = [_wide_tree(depth - 1, width, path / f"d{i}") for i in range(width)]
    return node


def test_tree_render_is_lazy_and_fast(qapp: QApplication, tmp_path: Path) -> None:
    view = _view(tmp_path)
    view._switch_mode("tree")
    # 40 x 40 x 40 x 40 = 2,5 M nodos potenciales: antes se creaban todos y la app se colgaba.
    view.tree_report = StorageHierarchyReport(root_node=_wide_tree(4, 40), formats=[], heaviest_files=[])
    t0 = time.monotonic()
    view._render_tree()
    assert time.monotonic() - t0 < 3.0
    root = view.folder_tree.topLevelItem(0)
    assert root.childCount() == 40
    first = root.child(0)
    assert first.childCount() == 0  # aun no cargado
    first.setExpanded(True)  # itemExpanded -> carga perezosa
    assert first.childCount() == 40
    assert len(view._tree_nodes) == 1 + 40 + 40


def test_analyzer_caps_children_and_heavy_list(tmp_path: Path) -> None:
    for i in range(8):
        d = tmp_path / f"d{i}"
        d.mkdir()
        (d / "f.bin").write_bytes(b"x" * (i + 1))
    rep = analyze_storage_hierarchy(tmp_path, max_children=3)
    assert len(rep.root_node.children) == 3
    assert rep.root_node.file_count == 8  # los totales incluyen todo
    assert rep.root_node.children[0].size_bytes == 8


def test_progress_emits_on_percent_increase(qapp: QApplication) -> None:
    seen: list[str] = []

    def _fn(progress_cb=None) -> int:
        for i in range(10, 60):
            progress_cb(i, f"etapa {i}")
        return 1

    task = workers.AsyncTask("t", _fn)
    from PySide6.QtCore import Qt

    task.signals.progress.connect(lambda _id, _p, s: seen.append(s), Qt.ConnectionType.DirectConnection)
    task.run()
    assert "etapa 59" in seen  # el texto ya no se queda congelado en una etapa vieja


def test_hang_watchdog_dumps_all_threads(tmp_path: Path) -> None:
    guard = CrashGuard(app_dir=tmp_path, version="9.9.9")
    guard.install()
    try:
        guard.start_hang_watchdog(threshold_s=0.3, poll_s=0.05)
        guard._last_ui_tick = time.monotonic() - 5  # simular hilo GUI sin responder
        deadline = time.monotonic() + 3
        while guard.hang_count == 0 and time.monotonic() < deadline:
            time.sleep(0.05)
        assert guard.hang_count == 1
        log = guard.crash_log_path.read_text(encoding="utf-8", errors="replace")
        assert "BLOQUEO DE INTERFAZ" in log and "MainThread" in log
        assert "test_hang_watchdog_dumps_all_threads" in log  # pila del hilo principal
    finally:
        guard.uninstall()


def test_anonymize_removes_personal_data(monkeypatch) -> None:
    monkeypatch.setenv("USERNAME", "datg2")
    monkeypatch.setenv("COMPUTERNAME", "LAPTOP-XYZ")
    text = (
        r"C:\Users\datg2\OneDrive - Fundacion Ejemplo\A S\x.py en LAPTOP-XYZ, "
        "correo persona@example.com, C:/Users/otra/AppData"
    )
    out = cr.anonymize_text(text)
    assert "datg2" not in out and "LAPTOP-XYZ" not in out and "Ejemplo" not in out
    assert "persona@example.com" not in out and "otra" not in out
    assert r"C:\Users\<usuario>\OneDrive - <organizacion>" in out


def test_issue_url_is_bounded_and_prefilled() -> None:
    body = "### Resumen\n" + ("linea de crash.log\n" * 3000)
    url, truncated = cr.build_issue_url("[Cierre inesperado] v0.5.3", body)
    assert truncated and len(url) <= cr.MAX_ISSUE_URL_CHARS
    q = parse_qs(urlparse(url).query)
    assert urlparse(url).netloc == "github.com" and q["labels"] == ["crash"]
    assert q["body"][0].startswith("### Resumen") and "portapapeles" in q["body"][0]
    short_url, short_trunc = cr.build_issue_url("t", "corto")
    assert not short_trunc and parse_qs(urlparse(short_url).query)["body"] == ["corto"]


def test_send_dialog_opens_github_only_on_user_click(qapp: QApplication, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("USERNAME", "datg2")
    guard = CrashGuard(app_dir=tmp_path, version="0.5.3")
    guard.begin_session()
    guard.write_log_block("PRUEBA", r"File C:\Users\datg2\proyecto\x.py line 1")
    guard2 = CrashGuard(app_dir=tmp_path, version="0.5.3")
    rep = guard2.begin_session()
    assert rep.dirty

    opened: list[str] = []
    decisions: list[bool] = []
    dlg = CrashSendDialog(guard2, on_decision=decisions.append, open_url=lambda u: opened.append(u) or True)
    assert opened == []  # nada se envia sin que el usuario pulse
    assert "datg2" not in dlg.report_text and "<usuario>" in dlg.report_text
    dlg._skip()
    assert opened == [] and decisions == [False]

    from winoptiai.ui.dialogs import crash_send_dialog as csd

    monkeypatch.setattr(csd.QMessageBox, "information", staticmethod(lambda *a, **k: None))
    dlg2 = CrashSendDialog(guard2, on_decision=decisions.append, open_url=lambda u: opened.append(u) or True)
    dlg2._send()
    assert dlg2.saved_path is not None and dlg2.saved_path.read_text(encoding="utf-8") == dlg2.report_text
    # v0.6.9: el informe se envia por correo (sin cuenta de GitHub)
    assert len(opened) == 1 and opened[0].startswith(f"mailto:{cr.REPORT_EMAIL}?") and decisions[-1] is True
    assert "datg2" not in opened[0]
    assert QApplication.clipboard().text() == dlg2.report_text


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_unhandled_exception_notifies_listener_once_per_type(tmp_path: Path) -> None:
    guard = CrashGuard(app_dir=tmp_path, version="0.5.3")
    got: list[tuple[str, str]] = []
    guard.add_unhandled_listener(lambda origin, et, _t: got.append((origin, et)))
    guard.install()
    try:
        t = threading.Thread(target=lambda: 1 / 0, name="worker-x")
        t.start()
        t.join()
    finally:
        guard.uninstall()
    assert ("threading:worker-x", "ZeroDivisionError") in got


@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_main_window_prompts_after_dirty_exit_and_dedupes_errors(qapp: QApplication, tmp_path: Path, monkeypatch) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from winoptiai.ui import main_window as mw

    guard = CrashGuard(app_dir=tmp_path / "g", version="0.5.3")
    guard.begin_session()
    guard2 = CrashGuard(app_dir=tmp_path / "g", version="0.5.3")
    guard2.begin_session()
    prompts: list[str] = []
    monkeypatch.setattr(mw.MainWindow, "_prompt_crash_report", lambda self, kind, **k: prompts.append(kind))
    monkeypatch.setattr(guard2, "query_recent_appcrash_events", lambda **k: [])
    win = mw.MainWindow(crash_guard=guard2)
    try:
        deadline = time.monotonic() + 8
        while mw.KIND_CRASH not in prompts and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.02)
        assert mw.KIND_CRASH in prompts

        for _ in range(3):
            win._on_unhandled_error("sys.excepthook", "ValueError", 'File "a.py", line 3\nValueError: x')
        win._on_unhandled_error("sys.excepthook", "KeyError", 'File "b.py", line 9\nKeyError: y')
        assert prompts.count(mw.KIND_ERROR) == 2
    finally:
        guard2.stop_hang_watchdog()
        win.heartbeat_timer.stop()
        win.deleteLater()
