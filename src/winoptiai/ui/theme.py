"""Dual-theme design system: Obsidian Acrylic (Dark) & Alabaster Frost (Light).

Strict 0px corners, 1px hairline borders, embedded Instrument Sans + IBM Plex Mono.
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from .. import get_base_dir


DARK_PALETTE = {
    "mode": "dark",
    "bg_window": "rgba(22, 22, 20, 224)",
    "bg_sidebar": "rgba(26, 26, 23, 212)",
    "bg_glass": "rgba(31, 31, 28, 184)",
    "bg_glass_elevated": "rgba(39, 38, 34, 204)",
    "bg_table": "rgba(24, 24, 21, 188)",
    "bg_table_alt": "rgba(32, 31, 28, 160)",
    "bg_header": "rgba(29, 28, 25, 226)",
    "bg_menu": "#1C1C19",
    "bg_hover": "rgba(234, 229, 218, 22)",
    "bg_active": "rgba(234, 229, 218, 36)",
    "border_hairline": "rgba(234, 229, 218, 38)",
    "border_strong": "rgba(234, 229, 218, 86)",
    "text_primary": "#EFEAE0",
    "text_secondary": "#B2ACA0",
    "text_muted": "#7D786E",
    "primary_bg": "#EAE5DA",
    "primary_fg": "#181815",
    "primary_hover": "#F8F4EC",
    "icon_color": "#E6E0D4",
    "icon_inverted": "#181815",
    "tag_ice": "#D4CFC4",
    "tag_warn": "#C89B62",
    "tag_risk": "#B86A6A",
    "tag_ok": "#8CA89A",
    "explorer_bg": "rgba(68, 128, 175, 48)",
    "explorer_border": "rgba(128, 182, 222, 120)",
    "explorer_hover": "rgba(68, 128, 175, 86)",
    "explorer_icon": "#A5D0F4",
}

LIGHT_PALETTE = {
    "mode": "light",
    "bg_window": "rgba(246, 242, 233, 236)",
    "bg_sidebar": "rgba(239, 234, 222, 224)",
    "bg_glass": "rgba(252, 250, 244, 198)",
    "bg_glass_elevated": "rgba(255, 253, 248, 228)",
    "bg_table": "rgba(253, 251, 246, 212)",
    "bg_table_alt": "rgba(242, 237, 226, 198)",
    "bg_header": "rgba(235, 229, 216, 235)",
    "bg_menu": "#FAF7F0",
    "bg_hover": "rgba(44, 42, 39, 16)",
    "bg_active": "rgba(44, 42, 39, 28)",
    "border_hairline": "rgba(44, 42, 39, 44)",
    "border_strong": "rgba(44, 42, 39, 92)",
    "text_primary": "#262421",
    "text_secondary": "#57534C",
    "text_muted": "#7A746A",
    "primary_bg": "#2B2926",
    "primary_fg": "#FAF7F0",
    "primary_hover": "#3D3A35",
    "icon_color": "#2D2B27",
    "icon_inverted": "#FAF7F0",
    "tag_ice": "#47443E",
    "tag_warn": "#A16207",
    "tag_risk": "#991B1B",
    "tag_ok": "#166534",
    "explorer_bg": "rgba(46, 98, 158, 24)",
    "explorer_border": "rgba(46, 98, 158, 118)",
    "explorer_hover": "rgba(46, 98, 158, 46)",
    "explorer_icon": "#1E4E8C",
}

# Backward-compatible default reference
PALETTE = DARK_PALETTE

UI_FONT_FAMILY = "Instrument Sans"
MONO_FONT_FAMILY = "IBM Plex Mono"


def get_palette(mode: str = "dark") -> dict[str, str]:
    return LIGHT_PALETTE if mode == "light" else DARK_PALETTE


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


def build_obsidian_qss(mode: str = "dark") -> str:
    """Return global QSS stylesheet enforcing 0px corners, 1px hairline borders, and glass surfaces."""
    p = get_palette(mode)
    return f"""
    * {{
        border-radius: 0px;
        font-family: "{UI_FONT_FAMILY}", "Segoe UI", sans-serif;
        outline: none;
    }}

    QMainWindow, QDialog {{
        background-color: {p["bg_window"]};
        color: {p["text_primary"]};
    }}

    QWidget#RootCanvas {{
        background-color: transparent;
        border: 1px solid {p["border_hairline"]};
    }}

    QWidget#Sidebar {{
        background-color: {p["bg_sidebar"]};
        border-right: 1px solid {p["border_hairline"]};
    }}

    QWidget#TopBar {{
        background-color: {p["bg_sidebar"]};
        border-bottom: 1px solid {p["border_hairline"]};
    }}

    QPushButton#ExplorerBtn {{
        background-color: {p["explorer_bg"]};
        border: 1px solid {p["explorer_border"]};
        padding: 6px 10px;
        min-width: 34px;
        max-width: 36px;
    }}

    QPushButton#ExplorerBtn:hover {{
        background-color: {p["explorer_hover"]};
        border-color: {p["explorer_icon"]};
    }}

    QPushButton#BellBtn {{
        background-color: {p["bg_glass_elevated"]};
        border: 1px solid {p["border_hairline"]};
        color: {p["text_primary"]};
        padding: 5px 10px;
        font-family: "{MONO_FONT_FAMILY}", monospace;
        font-size: 11px;
    }}

    QPushButton#BellBtn:hover {{
        background-color: {p["bg_hover"]};
        border-color: {p["border_strong"]};
    }}

    QWidget#GlassPanel {{
        background-color: {p["bg_glass"]};
        border: 1px solid {p["border_hairline"]};
    }}

    QWidget#GlassPanelElevated {{
        background-color: {p["bg_glass_elevated"]};
        border: 1px solid {p["border_hairline"]};
    }}

    QLabel {{
        color: {p["text_primary"]};
        background: transparent;
        border: none;
    }}

    QLabel#PageTitle {{
        font-size: 20px;
        font-weight: 600;
        letter-spacing: -0.3px;
        color: {p["text_primary"]};
    }}

    QLabel#PageSubtitle {{
        font-size: 12px;
        color: {p["text_secondary"]};
    }}

    QLabel#SectionLabel {{
        font-family: "{MONO_FONT_FAMILY}", monospace;
        font-size: 10px;
        font-weight: 500;
        letter-spacing: 1.2px;
        color: {p["text_muted"]};
    }}

    QLabel#MetricValue {{
        font-family: "{MONO_FONT_FAMILY}", monospace;
        font-size: 21px;
        font-weight: 500;
        color: {p["text_primary"]};
    }}

    QLabel#MonoValue {{
        font-family: "{MONO_FONT_FAMILY}", monospace;
        font-size: 12px;
        color: {p["text_primary"]};
    }}

    QPushButton#NavButton {{
        background-color: transparent;
        border: 1px solid transparent;
        color: {p["text_secondary"]};
        text-align: left;
        padding: 10px 14px;
        font-size: 13px;
        font-weight: 500;
    }}

    QPushButton#NavButton:hover {{
        background-color: {p["bg_hover"]};
        color: {p["text_primary"]};
    }}

    QPushButton#NavButton[active="true"] {{
        background-color: {p["bg_active"]};
        border-left: 2px solid {p["tag_ice"]};
        border-top: 1px solid {p["border_hairline"]};
        border-bottom: 1px solid {p["border_hairline"]};
        color: {p["text_primary"]};
    }}

    QPushButton#PrimaryAction {{
        background-color: {p["primary_bg"]};
        color: {p["primary_fg"]};
        border: 1px solid {p["primary_bg"]};
        padding: 9px 18px;
        font-size: 12px;
        font-weight: 600;
        letter-spacing: 0.2px;
    }}

    QPushButton#PrimaryAction:hover {{
        background-color: {p["primary_hover"]};
        border-color: {p["primary_hover"]};
    }}

    QPushButton#PrimaryAction:disabled {{
        opacity: 0.45;
    }}

    QPushButton#GhostAction {{
        background-color: {p["bg_glass_elevated"]};
        color: {p["text_primary"]};
        border: 1px solid {p["border_hairline"]};
        padding: 7px 12px;
        font-size: 12px;
        font-weight: 500;
    }}

    QPushButton#GhostAction:hover {{
        background-color: {p["bg_hover"]};
        border-color: {p["border_strong"]};
    }}

    QPushButton#GhostAction[selected="true"] {{
        background-color: {p["bg_active"]};
        border-color: {p["tag_ice"]};
    }}

    QComboBox {{
        background-color: {p["bg_glass_elevated"]};
        color: {p["text_primary"]};
        border: 1px solid {p["border_hairline"]};
        padding: 6px 10px;
        font-size: 12px;
    }}

    QComboBox QAbstractItemView {{
        background-color: {p["bg_menu"]};
        color: {p["text_primary"]};
        border: 1px solid {p["border_strong"]};
        selection-background-color: {p["bg_active"]};
    }}

    QTableWidget, QTreeWidget, QPlainTextEdit {{
        background-color: {p["bg_table"]};
        alternate-background-color: {p["bg_table_alt"]};
        color: {p["text_primary"]};
        gridline-color: {p["border_hairline"]};
        border: 1px solid {p["border_hairline"]};
        selection-background-color: {p["bg_active"]};
        selection-color: {p["text_primary"]};
        font-size: 12px;
    }}

    QHeaderView::section {{
        background-color: {p["bg_header"]};
        color: {p["text_secondary"]};
        font-family: "{MONO_FONT_FAMILY}", monospace;
        font-size: 10px;
        font-weight: 500;
        letter-spacing: 0.8px;
        padding: 8px 10px;
        border: none;
        border-right: 1px solid {p["border_hairline"]};
        border-bottom: 1px solid {p["border_hairline"]};
    }}

    QProgressBar {{
        background-color: {p["border_hairline"]};
        border: none;
        height: 3px;
        text-align: center;
    }}

    QProgressBar::chunk {{
        background-color: {p["tag_ice"]};
    }}

    QCheckBox {{
        color: {p["text_primary"]};
        spacing: 8px;
        font-size: 12px;
    }}

    QCheckBox::indicator {{
        width: 15px;
        height: 15px;
        border: 1px solid {p["border_strong"]};
        background-color: {p["bg_glass"]};
    }}

    QCheckBox::indicator:checked {{
        background-color: {p["primary_bg"]};
        border-color: {p["primary_bg"]};
    }}

    QScrollBar:vertical {{
        background: transparent;
        width: 8px;
        margin: 0px;
    }}

    QScrollBar::handle:vertical {{
        background: {p["border_strong"]};
        min-height: 24px;
    }}

    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {{
        height: 0px;
    }}

    QMenu {{
        background-color: {p["bg_menu"]};
        border: 1px solid {p["border_strong"]};
        color: {p["text_primary"]};
        padding: 4px;
    }}

    QMenu::item {{
        padding: 7px 16px;
        font-size: 12px;
    }}

    QMenu::item:selected {{
        background-color: {p["bg_active"]};
    }}
    """
