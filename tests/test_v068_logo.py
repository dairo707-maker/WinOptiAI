"""v0.6.8: logo propio de WinOptiAI (engranaje + escoba) separado del sello TRODAI."""

from __future__ import annotations

import os
import re
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from winoptiai import get_base_dir  # noqa: E402

LOGO = get_base_dir() / "assets" / "icons" / "winoptiai_logo.svg"


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def test_logo_is_pure_polygons_with_trodai_palette():
    txt = LOGO.read_text(encoding="utf-8")
    assert 'viewBox="0 0 64 64"' in txt
    # 100 % poligonal: sin curvas, circulos ni trazos libres
    assert not re.search(r"\b[CSQTA]\b|<(circle|ellipse|path)\b", txt)
    assert txt.count("<polygon") >= 8
    for color in ("#0F172A", "#475569", "#CBD5E1", "#F8FAFC", "#0EA5E9", "#34D399"):
        assert color in txt
    # El sello de la organizacion se conserva intacto
    assert (get_base_dir() / "assets" / "icons" / "brand.svg").exists()


def test_logo_renders_crisp_at_small_sizes(qapp):
    from winoptiai.ui.svg_icons import load_svg_pixmap

    for size in (16, 26, 40):
        pm = load_svg_pixmap("winoptiai_logo", size=size)
        assert not pm.isNull() and pm.width() >= size


def test_tray_icon_uses_logo(qapp):
    from winoptiai.ui.system_tray import build_high_contrast_tray_icon

    icon = build_high_contrast_tray_icon(light_taskbar=True)
    sizes = {s.width() for s in icon.availableSizes()}
    assert {16, 20, 24, 32}.issubset(sizes)


def test_sidebar_shows_logo_and_trodai_seal(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from winoptiai import __version__
    from winoptiai.ui.main_window import MainWindow

    win = MainWindow()
    try:
        assert not win.brand_icon.pixmap().isNull()
        assert not win.org_seal.pixmap().isNull()
        assert win.brand_sub.text() == f"v{__version__}"
    finally:
        win._force_quit = True
        win.close()


def test_build_script_rasterizes_logo_for_ico_and_installer():
    sys.path.insert(0, str(Path(get_base_dir()) / "scripts"))
    try:
        import build_exe
    finally:
        sys.path.pop(0)
    img = build_exe.render_logo(64)
    assert img is not None and img.size == (64, 64)
    # el centro debe ser el contenedor oscuro, no transparente
    r, g, b, a = img.getpixel((50, 40))
    assert a == 255 and max(r, g, b) < 90
