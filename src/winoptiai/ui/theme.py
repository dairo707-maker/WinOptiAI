"""Dual-theme design system: TRODAI Obsidian Navy (Dark) & Crisp White (Light).

Strict 0px architectural corners, 1px hairline borders, Space Grotesk + JetBrains Mono.
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from .. import get_base_dir


DARK_PALETTE = {
    "mode": "dark",
    "bg_window": "rgba(10, 15, 29, 236)",
    "bg_sidebar": "rgba(15, 22, 40, 228)",
    "bg_glass": "rgba(15, 22, 40, 214)",
    "bg_glass_elevated": "rgba(20, 29, 51, 232)",
    "bg_table": "rgba(10, 15, 29, 218)",
    "bg_table_alt": "rgba(20, 29, 51, 198)",
    "bg_header": "rgba(15, 22, 40, 242)",
    "bg_menu": "#0F1628",
    "bg_hover": "rgba(14, 165, 233, 24)",
    "bg_active": "rgba(14, 165, 233, 38)",
    "border_hairline": "#1F2A44",
    "border_strong": "#33415F",
    "text_primary": "#F8FAFC",
    "text_secondary": "#CBD5E1",
    "text_muted": "#94A3B8",
    "primary_bg": "#F8FAFC",
    "primary_fg": "#0A0F1D",
    "primary_hover": "#E2E8F0",
    "icon_color": "#F8FAFC",
    "icon_inverted": "#0A0F1D",
    "accent": "#0EA5E9",
    "accent_alt": "#3B82F6",
    "tag_ice": "#0EA5E9",
    "tag_warn": "#F59E0B",
    "tag_risk": "#F87171",
    "tag_ok": "#34D399",
    "explorer_bg": "rgba(14, 165, 233, 38)",
    "explorer_border": "#0EA5E9",
    "explorer_hover": "rgba(14, 165, 233, 68)",
    "explorer_icon": "#38BDF8",
}

LIGHT_PALETTE = {
    "mode": "light",
    "bg_window": "rgba(248, 250, 252, 244)",
    "bg_sidebar": "rgba(238, 242, 247, 238)",
    "bg_glass": "rgba(255, 255, 255, 238)",
    "bg_glass_elevated": "rgba(238, 242, 247, 242)",
    "bg_table": "rgba(255, 255, 255, 240)",
    "bg_table_alt": "rgba(241, 245, 249, 230)",
    "bg_header": "rgba(238, 242, 247, 246)",
    "bg_menu": "#FFFFFF",
    "bg_hover": "rgba(37, 99, 235, 18)",
    "bg_active": "rgba(37, 99, 235, 28)",
    "border_hairline": "#D5DCE6",
    "border_strong": "#AEB8C7",
    "text_primary": "#0A0F1D",
    "text_secondary": "#334155",
    "text_muted": "#4A5568",
    "primary_bg": "#0A0F1D",
    "primary_fg": "#F8FAFC",
    "primary_hover": "#1E293B",
    "icon_color": "#0A0F1D",
    "icon_inverted": "#F8FAFC",
    "accent": "#2563EB",
    "accent_alt": "#3B82F6",
    "tag_ice": "#2563EB",
    "tag_warn": "#B45309",
    "tag_risk": "#B91C1C",
    "tag_ok": "#047857",
    "explorer_bg": "rgba(37, 99, 235, 24)",
    "explorer_border": "#3B82F6",
    "explorer_hover": "rgba(37, 99, 235, 48)",
    "explorer_icon": "#1D4ED8",
}

# Backward-compatible default reference
PALETTE = DARK_PALETTE

UI_FONT_FAMILY = "Space Grotesk"
MONO_FONT_FAMILY = "JetBrains Mono"


def get_palette(mode: str = "dark") -> dict[str, str]:
    return LIGHT_PALETTE if mode == "light" else DARK_PALETTE


def register_embedded_fonts(app: QApplication) -> None:
    """Load bundled OFL fonts (Space Grotesk + JetBrains Mono + fallbacks) into Qt font database."""
    fonts_dir = get_base_dir() / "assets" / "fonts"
    if not fonts_dir.exists():
        return

    for font_file in sorted(fonts_dir.glob("*.ttf")):
        QFontDatabase.addApplicationFont(str(font_file))

    families = set(QFontDatabase.families())
    chosen = UI_FONT_FAMILY if UI_FONT_FAMILY in families else "Instrument Sans"
    base_font = QFont(chosen, 10)
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
    """Return global QSS stylesheet enforcing 0px TRODAI corners, 1px borders, and corporate palette."""
    p = get_palette(mode)
    return f"""
    * {{
        border-radius: 0px;
        font-family: "{UI_FONT_FAMILY}", "Instrument Sans", "Segoe UI", sans-serif;
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

    QWidget#UpdateBanner {{
        background-color: {_rgba(p["accent"], 26)};
        border-bottom: 1px solid {_rgba(p["accent"], 120)};
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
        font-family: "{MONO_FONT_FAMILY}", "IBM Plex Mono", monospace;
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

    /* v0.6.1 Jerarquia tipografica unica (Space Grotesk solo trae Light/Regular/Medium/Bold;
       JetBrains Mono no trae Bold): titulos 700, cuerpo 400, secundarios 300, botones 500.
       Nunca usar 600: Qt lo resuelve distinto segun la fuente y se ve "raro". */
    QLabel#PageTitle {{
        font-size: 19px;
        font-weight: 700;
        letter-spacing: -0.3px;
        color: {p["text_primary"]};
    }}

    QLabel#PageSubtitle, QLabel#BodyText {{
        font-size: 12px;
        font-weight: 400;
        color: {p["text_secondary"]};
    }}

    QLabel#CardTitle {{
        font-size: 13px;
        font-weight: 700;
        color: {p["text_primary"]};
    }}

    QLabel#SectionLabel {{
        font-family: "{UI_FONT_FAMILY}", "Instrument Sans", "Segoe UI", sans-serif;
        font-size: 10px;
        font-weight: 700;
        letter-spacing: 0.6px;
        color: {p["text_secondary"]};
    }}

    QLabel#Caption {{
        font-size: 10.5px;
        font-weight: 300;
        letter-spacing: 0.4px;
        color: {p["text_muted"]};
    }}

    QLabel#MetricValue {{
        font-family: "{MONO_FONT_FAMILY}", "IBM Plex Mono", monospace;
        font-size: 20px;
        font-weight: 500;
        color: {p["text_primary"]};
    }}

    QLabel#MetricValueCompact {{
        font-family: "{MONO_FONT_FAMILY}", "IBM Plex Mono", monospace;
        font-size: 14px;
        font-weight: 500;
        color: {p["text_primary"]};
    }}

    QLabel#MonoValue {{
        font-family: "{MONO_FONT_FAMILY}", "IBM Plex Mono", monospace;
        font-size: 11.5px;
        color: {p["text_primary"]};
    }}

    QPushButton#NavButton {{
        background-color: transparent;
        border: 1px solid transparent;
        color: {p["text_secondary"]};
        text-align: left;
        padding: 8px 12px;
        font-size: 12.5px;
        font-weight: 500;
    }}

    QPushButton#NavButton:hover {{
        background-color: {p["bg_hover"]};
        color: {p["text_primary"]};
    }}

    QPushButton#NavButton[active="true"] {{
        background-color: {p["bg_active"]};
        border-left: 2px solid {p["accent"]};
        border-top: 1px solid {p["border_hairline"]};
        border-bottom: 1px solid {p["border_hairline"]};
        color: {p["text_primary"]};
    }}

    QPushButton#PrimaryAction {{
        background-color: {p["primary_bg"]};
        color: {p["primary_fg"]};
        border: 1px solid {p["primary_bg"]};
        padding: 8px 16px;
        font-size: 12px;
        font-weight: 700;
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
        padding: 6px 11px;
        font-size: 12px;
        font-weight: 500;
    }}

    QPushButton#GhostAction:hover {{
        background-color: {p["bg_hover"]};
        border-color: {p["accent"]};
    }}

    QPushButton#GhostAction[selected="true"] {{
        background-color: {p["bg_active"]};
        border-color: {p["accent"]};
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
        border-bottom: 2px solid {p["accent"]};
        font-weight: 700;
    }}

    /* v0.5.6: acciones especificas de cada pestana segun su efecto (tonos apagados, sin neon). */
    QPushButton#RestoreAction, QPushButton#MoveAction, QPushButton#RiskAction {{
        padding: 7px 12px;
        font-size: 12px;
        font-weight: 700;
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

    /* Controles minimalistas de tema e idioma en barra superior (v0.6.1). */
    QWidget#TopBar QPushButton#TopUtilityBtn {{
        background-color: transparent;
        border: 1px solid transparent;
        padding: 0px;
        border-radius: 6px;
    }}

    QWidget#TopBar QPushButton#TopUtilityBtn:hover {{
        background-color: {p["bg_hover"]};
        border-color: {p["border_hairline"]};
    }}

    QWidget#TopBar QComboBox#TopLangCombo {{
        background-color: transparent;
        color: {p["text_secondary"]};
        border: 1px solid {p["border_hairline"]};
        border-radius: 6px;
        padding: 2px 14px 2px 8px;
        font-size: 11px;
        font-weight: 500;
    }}

    QWidget#TopBar QComboBox#TopLangCombo:hover {{
        background-color: {p["bg_hover"]};
        color: {p["text_primary"]};
        border-color: {p["border_strong"]};
    }}

    QWidget#TopBar QComboBox#TopLangCombo::drop-down {{
        subcontrol-origin: padding;
        subcontrol-position: center right;
        width: 14px;
        border: none;
        background: transparent;
    }}

    QWidget#TopBar QComboBox#TopLangCombo::down-arrow {{
        width: 0px;
        height: 0px;
        border-left: 3px solid transparent;
        border-right: 3px solid transparent;
        border-top: 4px solid {p["text_secondary"]};
        margin-right: 4px;
    }}

    QComboBox#TopLangCombo QAbstractItemView {{
        border-radius: 0px;
    }}

    QComboBox, QLineEdit {{
        background-color: {p["bg_glass_elevated"]};
        color: {p["text_primary"]};
        border: 1px solid {p["border_hairline"]};
        padding: 6px 10px;
        font-size: 12px;
    }}

    QLineEdit:focus {{
        border-color: {p["accent"]};
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
        font-family: "{MONO_FONT_FAMILY}", "IBM Plex Mono", monospace;
        font-size: 10px;
        font-weight: 500;
        letter-spacing: 0.8px;
        padding: 7px 9px;
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
        background-color: {p["accent"]};
    }}

    QProgressBar[tone="ok"]::chunk {{
        background-color: {p["tag_ok"]};
    }}

    QProgressBar[tone="warn"]::chunk {{
        background-color: {p["tag_warn"]};
    }}

    QProgressBar[tone="risk"]::chunk {{
        background-color: {p["tag_risk"]};
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
        background-color: {p["accent"]};
        border-color: {p["accent"]};
    }}

    QCheckBox::indicator:indeterminate {{
        background-color: {p["border_strong"]};
        border-color: {p["accent"]};
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

    QTabWidget::pane {{
        border: 1px solid {p["border_hairline"]};
        background-color: transparent;
    }}

    QTabBar::tab {{
        background-color: transparent;
        color: {p["text_secondary"]};
        border: 1px solid {p["border_hairline"]};
        padding: 6px 12px;
        font-family: "{MONO_FONT_FAMILY}", "IBM Plex Mono", monospace;
        font-size: 11px;
        margin-right: 4px;
    }}

    QTabBar::tab:selected {{
        background-color: {p["bg_active"]};
        color: {p["text_primary"]};
        border-bottom: 2px solid {p["accent"]};
    }}

    QToolTip {{
        background-color: {p["bg_menu"]};
        color: {p["text_primary"]};
        border: 1px solid {p["accent"]};
        border-radius: 0px;
        padding: 8px 10px;
        font-family: "{UI_FONT_FAMILY}", "Instrument Sans", "Segoe UI", sans-serif;
        font-size: 12px;
    }}
    """
