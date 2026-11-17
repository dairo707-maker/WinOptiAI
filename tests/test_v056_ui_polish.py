"""WinOptiAI v0.5.6: botones nunca recortados (oscuro/claro, ventana minima), roles de accion y barra superior."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton, QWidget  # noqa: E402

from winoptiai.ui.theme import build_obsidian_qss, register_embedded_fonts  # noqa: E402
from winoptiai.ui.widgets import AdaptiveButton, FlowLayout, find_clipped_buttons  # noqa: E402


@pytest.fixture(scope="module")
def qapp() -> QApplication:
    app = QApplication.instance() or QApplication([])
    register_embedded_fonts(app)
    return app


def _pump(app: QApplication, n: int = 6) -> None:
    for _ in range(n):
        app.processEvents()


def test_adaptive_button_picks_variant_that_fits(qapp: QApplication) -> None:
    qapp.setStyleSheet(build_obsidian_qss("dark"))
    holder = QWidget()
    b = AdaptiveButton("Elevar Admin (UAC)", holder)
    b.setObjectName("GhostAction")
    b.set_variants(["Elevar Admin (UAC)", "Elevar Admin", "Admin"])
    b.resize(b.sizeHint())
    holder.show()
    _pump(qapp)
    assert b.text() == "Elevar Admin (UAC)"
    b.resize(b.hint_for("Admin") + 2, b.height())
    _pump(qapp)
    assert b.text() == "Admin" and "Elevar Admin (UAC)" in b.toolTip()
    assert find_clipped_buttons(holder) == []
    b.setText("Reanudar")  # setText sigue funcionando como en QPushButton
    assert b.variants() == ["Reanudar"]


def test_flow_layout_wraps_instead_of_clipping(qapp: QApplication) -> None:
    holder = QWidget()
    flow = FlowLayout(holder, spacing=6)
    btns = [QPushButton(f"Pestana numero {i}") for i in range(6)]
    for b in btns:
        flow.addWidget(b)
    holder.resize(360, flow.heightForWidth(360))
    holder.show()
    _pump(qapp)
    assert find_clipped_buttons(holder) == []
    rows = {b.y() for b in btns}
    assert len(rows) >= 2  # paso a varias filas


@pytest.mark.parametrize("mode", ["dark", "light"])
def test_no_clipped_buttons_in_any_view_at_minimum_size(qapp: QApplication, tmp_path: Path, monkeypatch, mode: str) -> None:
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from winoptiai.ui.main_window import MainWindow, _task_pill_variants

    win = MainWindow()
    try:
        win.policy.config.theme_mode = mode
        qapp.setStyleSheet(build_obsidian_qss(mode))
        win.resize(980, 650)
        win.show()
        _pump(qapp, 10)
        problems: list[tuple[str, tuple]] = []
        for i in range(4):
            win._switch_tab(i)
            _pump(qapp)
            problems += [(f"tab{i}", p) for p in find_clipped_buttons(win)]
        win._switch_tab(1)
        for m in ["junk", "duplicates", "tree", "orphans", "quarantine", "onedrive"]:
            win.storage_view._switch_mode(m)
            _pump(qapp)
            problems += [(m, p) for p in find_clipped_buttons(win)]
        # barra superior con todas las acciones de tareas visibles
        for b in (win.pause_top_btn, win.save_pause_top_btn, win.cancel_top_btn, win.resume_session_btn):
            b.setVisible(True)
        win.task_pill_btn.set_variants(_task_pill_variants("Arbol almacenamiento ()", 51, " · ~3s rest.", " (+1)"))
        win.resume_session_btn.set_variants(["Retomar Sesion (2)", "Retomar (2)", "Retomar"])
        _pump(qapp, 10)
        problems += [("topbar", p) for p in find_clipped_buttons(win)]
        assert problems == []
    finally:
        win.heartbeat_timer.stop()
        win.telemetry_timer.stop()
        win.hide()
        win.deleteLater()


def test_tab_specific_actions_have_semantic_roles(qapp: QApplication, tmp_path: Path) -> None:
    from winoptiai.core.safety_guard import PreOpBackupManager, QuarantineVault
    from winoptiai.core.sre_policy import SREPolicyEngine
    from winoptiai.ui.views.storage_view import StorageView

    v = StorageView(
        QuarantineVault(root_dir=tmp_path), PreOpBackupManager(root_dir=tmp_path), SREPolicyEngine(app_dir=tmp_path),
        lambda *a, **k: None, lambda _m: None,
    )
    v._switch_mode("quarantine")
    assert v.secondary_btn.objectName() == "RestoreAction"
    assert v.tertiary_btn.objectName() == "RiskAction"
    v._switch_mode("duplicates")
    assert v.secondary_btn.objectName() == "MoveAction" and v.tertiary_btn.objectName() == "MoveAction"
    assert {b.objectName() for b in v.mode_buttons.values()} == {"ModeTab"}


def test_qss_rounds_only_top_bar_and_defines_roles() -> None:
    for mode in ("dark", "light"):
        qss = build_obsidian_qss(mode)
        assert "QWidget#TopBar QPushButton" in qss and "border-radius: 6px" in qss
        for role in ("RestoreAction", "MoveAction", "RiskAction", "ModeTab"):
            assert f"QPushButton#{role}" in qss
        assert "border-radius: 0px" in qss  # el resto sigue recto
