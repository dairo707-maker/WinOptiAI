"""Obsidian Acrylic design system: strict 0px geometry, Instrument Sans + IBM Plex Mono."""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from .. import get_base_dir


PALETTE = {
    "bg_window": "rgba(11, 13, 16, 218)",
    "bg_sidebar": "rgba(15, 18, 23, 210)",
    "bg_glass": "rgba(22, 26, 33, 175)",
    "bg_glass_elevated": "rgba(30, 35, 44, 195)",
    "bg_hover": "rgba(216, 224, 234, 20)",
    "bg_active": "rgba(216, 224, 234, 34)",
    "border_hairline": "rgba(255, 255, 255, 24)",
    "border_strong": "rgba(216, 224, 234, 68)",
    "text_primary": "#F1F3F5",
    "text_secondary": "#9BA3AE",
    "text_muted": "#646D78",
    "tag_ice": "#CBD5E1",
    "tag_warn": "#C89B62",
    "tag_risk": "#B86A6A",
    "tag_ok": "#8CA89A",
}

UI_FONT_FAMILY = "Instrument Sans"
MONO_FONT_FAMILY = "IBM Plex Mono"


def register_embedded_fonts(app: QApplication) -> None:
    """Load bundled OFL fonts (Instrument Sans + IBM Plex Mono) into Qt font database."""
    fonts_dir = get_base_dir() / "assets" / "fonts"
    if not fonts_dir.exists():
        return

    for font_file in sorted(fonts_dir.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(font_file))

    base_font = QFont(UI_FONT_FAMILY, 10)
    base_font.setStyleStrategy(QFont.StyleStrategy.PreferAntialias)
    app.setFont(base_font)


def format_bytes(num_bytes: int | float) -> str:
    """Format byte counts cleanly with tabular unit labels."""
    val = float(max(0, num_bytes))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if val < 1024.0 or unit == "TB":
            if unit in ("B", "KB"):
                return f"{val:.0f} {unit}"
            return f"{val:.2f} {unit}"
        val /= 1024.0
    return f"{val:.2f} TB"


def build_obsidian_qss() -> str:
    """Return global QSS stylesheet enforcing 0px corners, 1px hairline borders, and glass surfaces."""
    return f"""
    * {{
        border-radius: 0px;
        font-family: "{UI_FONT_FAMILY}", "Segoe UI", sans-serif;
        outline: none;
    }}

    QMainWindow, QDialog {{
        background-color: {PALETTE["bg_window"]};
        color: {PALETTE["text_primary"]};
    }}

    QWidget#RootCanvas {{
        background-color: {PALETTE["bg_window"]};
        border: 1px solid {PALETTE["border_hairline"]};
    }}

    QWidget#Sidebar {{
        background-color: {PALETTE["bg_sidebar"]};
        border-right: 1px solid {PALETTE["border_hairline"]};
    }}

    QWidget#GlassPanel {{
        background-color: {PALETTE["bg_glass"]};
        border: 1px solid {PALETTE["border_hairline"]};
    }}

    QWidget#GlassPanelElevated {{
        background-color: {PALETTE["bg_glass_elevated"]};
        border: 1px solid {PALETTE["border_hairline"]};
    }}

    QLabel {{
        color: {PALETTE["text_primary"]};
        background: transparent;
        border: none;
    }}

    QLabel#PageTitle {{
        font-size: 20px;
        font-weight: 600;
        letter-spacing: -0.3px;
        color: {PALETTE["text_primary"]};
    }}

    QLabel#PageSubtitle {{
        font-size: 12px;
        color: {PALETTE["text_secondary"]};
    }}

    QLabel#SectionLabel {{
        font-family: "{MONO_FONT_FAMILY}", monospace;
        font-size: 10px;
        font-weight: 500;
        letter-spacing: 1.2px;
        color: {PALETTE["text_muted"]};
    }}

    QLabel#MetricValue {{
        font-family: "{MONO_FONT_FAMILY}", monospace;
        font-size: 22px;
        font-weight: 500;
        color: {PALETTE["text_primary"]};
    }}

    QLabel#MonoValue {{
        font-family: "{MONO_FONT_FAMILY}", monospace;
        font-size: 12px;
        color: {PALETTE["text_primary"]};
    }}

    QPushButton#NavButton {{
        background-color: transparent;
        border: 1px solid transparent;
        color: {PALETTE["text_secondary"]};
        text-align: left;
        padding: 10px 14px;
        font-size: 13px;
        font-weight: 500;
    }}

    QPushButton#NavButton:hover {{
        background-color: {PALETTE["bg_hover"]};
        color: {PALETTE["text_primary"]};
    }}

    QPushButton#NavButton[active="true"] {{
        background-color: {PALETTE["bg_active"]};
        border-left: 2px solid {PALETTE["tag_ice"]};
        border-top: 1px solid {PALETTE["border_hairline"]};
        border-bottom: 1px solid {PALETTE["border_hairline"]};
        color: {PALETTE["text_primary"]};
    }}

    QPushButton#PrimaryAction {{
        background-color: #E2E7ED;
        color: #0B0D10;
        border: 1px solid #E2E7ED;
        padding: 9px 18px;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.2px;
    }}

    QPushButton#PrimaryAction:hover {{
        background-color: #FFFFFF;
        border-color: #FFFFFF;
    }}

    QPushButton#PrimaryAction:disabled {{
        background-color: rgba(226, 231, 237, 45);
        border-color: rgba(226, 231, 237, 45);
        color: rgba(11, 13, 16, 140);
    }}

    QPushButton#GhostAction {{
        background-color: {PALETTE["bg_glass_elevated"]};
        color: {PALETTE["text_primary"]};
        border: 1px solid {PALETTE["border_hairline"]};
        padding: 8px 14px;
        font-size: 12px;
        font-weight: 500;
    }}

    QPushButton#GhostAction:hover {{
        background-color: {PALETTE["bg_hover"]};
        border-color: {PALETTE["border_strong"]};
    }}

    QPushButton#GhostAction[selected="true"] {{
        background-color: {PALETTE["bg_active"]};
        border-color: {PALETTE["tag_ice"]};
    }}

    QTableWidget {{
        background-color: rgba(13, 16, 20, 165);
        alternate-background-color: rgba(20, 24, 30, 140);
        color: {PALETTE["text_primary"]};
        gridline-color: rgba(255, 255, 255, 14);
        border: 1px solid {PALETTE["border_hairline"]};
        selection-background-color: rgba(216, 224, 234, 38);
        selection-color: #FFFFFF;
        font-size: 12px;
    }}

    QHeaderView::section {{
        background-color: rgba(19, 23, 29, 220);
        color: {PALETTE["text_secondary"]};
        font-family: "{MONO_FONT_FAMILY}", monospace;
        font-size: 10px;
        font-weight: 500;
        letter-spacing: 0.8px;
        padding: 8px 10px;
        border: none;
        border-right: 1px solid rgba(255, 255, 255, 14);
        border-bottom: 1px solid {PALETTE["border_hairline"]};
    }}

    QProgressBar {{
        background-color: rgba(255, 255, 255, 18);
        border: none;
        height: 3px;
        text-align: center;
    }}

    QProgressBar::chunk {{
        background-color: {PALETTE["tag_ice"]};
    }}

    QCheckBox {{
        color: {PALETTE["text_primary"]};
        spacing: 8px;
        font-size: 12px;
    }}

    QCheckBox::indicator {{
        width: 15px;
        height: 15px;
        border: 1px solid {PALETTE["border_strong"]};
        background-color: rgba(15, 18, 23, 200);
    }}

    QCheckBox::indicator:checked {{
        background-color: #E2E7ED;
        border-color: #E2E7ED;
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0px;
    }}

    QScrollBar::handle:vertical {{
        background: rgba(255, 255, 255, 38);
        min-height: 24px;
    }}

    QScrollBar::handle:vertical:hover {{
        background: rgba(255, 255, 255, 68);
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QMenu {{
        background-color: #12161C;
        border: 1px solid {PALETTE["border_strong"]};
        color: {PALETTE["text_primary"]};
        padding: 4px;
    }}

    QMenu::item {{
        padding: 7px 16px;
        font-size: 12px;
    }}

    QMenu::item:selected {{
        background-color: {PALETTE["bg_active"]};
    }}
    """
