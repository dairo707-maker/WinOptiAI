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
    "bg_sidebar": "rgba(26, 26, 23, 214)",
    "bg_glass": "rgba(31, 31, 28, 190)",
    "bg_glass_elevated": "rgba(39, 38, 34, 212)",
    "bg_table": "rgba(24, 24, 21, 196)",
    "bg_table_alt": "rgba(33, 32, 29, 170)",
    "bg_header": "rgba(29, 28, 25, 232)",
    "bg_menu": "#1C1C19",
    "bg_hover": "rgba(234, 229, 218, 24)",
    "bg_active": "rgba(234, 229, 218, 42)",
    "border_hairline": "rgba(234, 229, 218, 52)",
    "border_strong": "rgba(234, 229, 218, 110)",
    "text_primary": "#F3EFE6",
    "text_secondary": "#C2BCB0",
    "text_muted": "#8C867A",
    "primary_bg": "#EFEAE0",
    "primary_fg": "#171714",
    "primary_hover": "#FAF7F0",
    "icon_color": "#EFEAE0",
    "icon_inverted": "#171714",
    "tag_ice": "#DFDAD0",
    "tag_warn": "#D9A86C",
    "tag_risk": "#CF7C7C",
    "tag_ok": "#99BAAB",
    "explorer_bg": "rgba(44, 108, 164, 72)",
    "explorer_border": "rgba(147, 197, 253, 170)",
    "explorer_hover": "rgba(44, 108, 164, 115)",
    "explorer_icon": "#BAE6FD",
}

LIGHT_PALETTE = {
    "mode": "light",
    "bg_window": "rgba(245, 241, 231, 236)",
    "bg_sidebar": "rgba(237, 232, 219, 228)",
    "bg_glass": "rgba(253, 251, 246, 206)",
    "bg_glass_elevated": "rgba(255, 253, 249, 236)",
    "bg_table": "rgba(254, 252, 247, 220)",
    "bg_table_alt": "rgba(242, 237, 226, 206)",
    "bg_header": "rgba(232, 226, 212, 240)",
    "bg_menu": "#FAF7F0",
    "bg_hover": "rgba(38, 36, 32, 18)",
    "bg_active": "rgba(38, 36, 32, 32)",
    "border_hairline": "rgba(38, 36, 32, 62)",
    "border_strong": "rgba(38, 36, 32, 125)",
    "text_primary": "#1C1B18",
    "text_secondary": "#46433C",
    "text_muted": "#6E695E",
    "primary_bg": "#1F1E1B",
    "primary_fg": "#FAF7F0",
    "primary_hover": "#34322D",
    "icon_color": "#1F1E1B",
    "icon_inverted": "#FAF7F0",
    "tag_ice": "#3F3D37",
    "tag_warn": "#9A5B13",
    "tag_risk": "#991B1B",
    "tag_ok": "#145A32",
    "explorer_bg": "rgba(29, 78, 137, 36)",
    "explorer_border": "rgba(29, 78, 137, 155)",
    "explorer_hover": "rgba(29, 78, 137, 62)",
    "explorer_icon": "#143D73",
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


def _rgba(hex_color: str, alpha: int) -> str:
    """'#RRGGBB' -> 'rgba(r, g, b, a)' para tintes suaves de los roles de accion."""
    h = hex_color.lstrip("#")
    if len(h) != 6:
        return hex_color
    r, g, b = int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)
    return f"rgba({r}, {g}, {b}, {max(0, min(255, alpha))})"


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

    QLabel#MetricValueCompact {{
        font-family: "{MONO_FONT_FAMILY}", monospace;
        font-size: 18px;
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

    /* v0.5.6: pestanas de modo (navegacion dentro de una vista): planas, subrayado al activarse. */
    QPushButton#ModeTab {{
        background-color: transparent;
        color: {p["text_secondary"]};
        border: 1px solid {p["border_hairline"]};
        padding: 7px 12px;
        font-size: 12px;
        font-weight: 500;
    }}

    QPushButton#ModeTab:hover {{
        background-color: {p["bg_hover"]};
        color: {p["text_primary"]};
    }}

    QPushButton#ModeTab[selected="true"] {{
        background-color: {p["bg_active"]};
        color: {p["text_primary"]};
        border-color: {p["border_strong"]};
        border-bottom: 2px solid {p["tag_ice"]};
        font-weight: 600;
    }}

    /* v0.5.6: acciones especificas de cada pestana segun su efecto (tonos apagados, sin neon). */
    QPushButton#RestoreAction, QPushButton#MoveAction, QPushButton#RiskAction {{
        padding: 7px 12px;
        font-size: 12px;
        font-weight: 600;
        border-left-width: 3px;
    }}

    QPushButton#RestoreAction {{
        background-color: {_rgba(p["tag_ok"], 22)};
        color: {p["tag_ok"]};
        border: 1px solid {_rgba(p["tag_ok"], 120)};
        border-left: 3px solid {p["tag_ok"]};
    }}

    QPushButton#RestoreAction:hover {{
        background-color: {_rgba(p["tag_ok"], 44)};
    }}

    QPushButton#MoveAction {{
        background-color: {_rgba(p["tag_warn"], 20)};
        color: {p["tag_warn"]};
        border: 1px solid {_rgba(p["tag_warn"], 120)};
        border-left: 3px solid {p["tag_warn"]};
    }}

    QPushButton#MoveAction:hover {{
        background-color: {_rgba(p["tag_warn"], 42)};
    }}

    QPushButton#RiskAction {{
        background-color: {_rgba(p["tag_risk"], 22)};
        color: {p["tag_risk"]};
        border: 1px solid {_rgba(p["tag_risk"], 130)};
        border-left: 3px solid {p["tag_risk"]};
    }}

    QPushButton#RiskAction:hover {{
        background-color: {_rgba(p["tag_risk"], 46)};
    }}

    QPushButton#RestoreAction:disabled, QPushButton#MoveAction:disabled, QPushButton#RiskAction:disabled {{
        background-color: transparent;
        color: {p["text_muted"]};
        border-color: {p["border_hairline"]};
    }}

    /* v0.5.6 (decision del propietario): panel superior con bordes semirredondos. */
    QWidget#TopBar QPushButton {{
        border-radius: 6px;
    }}

    QWidget#TopBar QLabel {{
        border-radius: 5px;
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

    QCheckBox::indicator:indeterminate {{
        background-color: {p["border_strong"]};
        border-color: {p["primary_bg"]};
    }}

    QCheckBox::indicator {{
        border-radius: 0px;
    }}

    QCheckBox:disabled {{
        color: {p["text_secondary"]};
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
