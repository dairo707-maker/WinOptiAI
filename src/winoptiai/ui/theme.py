"""Dual-theme design system: Obsidian Acrylic (Dark) & Alabaster Frost (Light).

Strict 0px corners, 1px hairline borders, embedded Instrument Sans + IBM Plex Mono.
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from .. import get_base_dir


DARK_PALETTE = {
    "mode": "dark",
    "bg_window": "rgba(11, 13, 16, 218)",
    "bg_sidebar": "rgba(15, 18, 23, 212)",
    "bg_glass": "rgba(22, 26, 33, 178)",
    "bg_glass_elevated": "rgba(30, 35, 44, 198)",
    "bg_table": "rgba(13, 16, 20, 170)",
    "bg_table_alt": "rgba(20, 24, 30, 145)",
    "bg_header": "rgba(19, 23, 29, 224)",
    "bg_menu": "#12161C",
    "bg_hover": "rgba(216, 224, 234, 22)",
    "bg_active": "rgba(216, 224, 234, 36)",
    "border_hairline": "rgba(255, 255, 255, 24)",
    "border_strong": "rgba(216, 224, 234, 72)",
    "text_primary": "#F1F3F5",
    "text_secondary": "#9BA3AE",
    "text_muted": "#646D78",
    "primary_bg": "#E2E7ED",
    "primary_fg": "#0B0D10",
    "primary_hover": "#FFFFFF",
    "icon_color": "#D8E0EA",
    "icon_inverted": "#0B0D10",
    "tag_ice": "#CBD5E1",
    "tag_warn": "#C89B62",
    "tag_risk": "#B86A6A",
    "tag_ok": "#8CA89A",
}

LIGHT_PALETTE = {
    "mode": "light",
    "bg_window": "rgba(244, 246, 248, 236)",
    "bg_sidebar": "rgba(235, 239, 243, 232)",
    "bg_glass": "rgba(255, 255, 255, 192)",
    "bg_glass_elevated": "rgba(248, 250, 252, 225)",
    "bg_table": "rgba(255, 255, 255, 205)",
    "bg_table_alt": "rgba(240, 243, 247, 195)",
    "bg_header": "rgba(232, 236, 241, 235)",
    "bg_menu": "#F8FAFC",
    "bg_hover": "rgba(17, 22, 29, 14)",
    "bg_active": "rgba(17, 22, 29, 24)",
    "border_hairline": "rgba(17, 22, 29, 28)",
    "border_strong": "rgba(17, 22, 29, 75)",
    "text_primary": "#11161D",
    "text_secondary": "#4B5563",
    "text_muted": "#6B7280",
    "primary_bg": "#11161D",
    "primary_fg": "#F8FAFC",
    "primary_hover": "#242D38",
    "icon_color": "#1E2530",
    "icon_inverted": "#F8FAFC",
    "tag_ice": "#334155",
    "tag_warn": "#A16207",
    "tag_risk": "#991B1B",
    "tag_ok": "#166534",
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
        background-color: {p["bg_window"]};
        border: 1px solid {p["border_hairline"]};
    }}

    QWidget#Sidebar {{
        background-color: {p["bg_sidebar"]};
        border-right: 1px solid {p["border_hairline"]};
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
