"""Dual-theme design system: TRODAI Obsidian Navy (Dark) & Crisp White (Light).

Strict 0px architectural corners, 1px hairline borders, Space Grotesk + JetBrains Mono.
"""

from __future__ import annotations

from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from .. import get_base_dir


DARK_PALETTE = {
    "mode": "dark",
    "bg_window": "#0B0F19",
    "bg_sidebar": "#101624",
    "bg_glass": "#131B2C",
    "bg_glass_elevated": "#182234",
    "bg_table": "#0D1322",
    "bg_table_alt": "#131B2C",
    "bg_header": "#101624",
    "bg_menu": "#101624",
    "bg_track": "#0D121E",
    "bg_hover": "#182234",
    "bg_active": "#212D44",
    "border_hairline": "#1F2A3E",
    "border_strong": "#334155",
    "border_selected": "#64748B",
    "text_primary": "#F8FAFC",
    "text_secondary": "#CBD5E1",
    "text_muted": "#94A3B8",
    "primary_bg": "#F8FAFC",
    "primary_fg": "#0B0F19",
    "primary_hover": "#E2E8F0",
    "icon_color": "#F8FAFC",
    "icon_inverted": "#0B0F19",
    "accent": "#0EA5E9",
    "accent_alt": "#3B82F6",
    "motion_cyan": "#0EA5E9",
    "motion_blue": "#3B82F6",
    "tag_ice": "#0EA5E9",
    "tag_warn": "#FCD34D",
    "tag_risk": "#FCA5A5",
    "tag_ok": "#6EE7B7",
    "restore_bg": "#152E28",
    "restore_bd": "#2B6A5A",
    "restore_hover": "#1C3D35",
    "move_bg": "#352814",
    "move_bd": "#78561F",
    "move_hover": "#46351A",
    "risk_bg": "#3A191E",
    "risk_bd": "#7F2933",
    "risk_hover": "#4B2027",
    "explorer_bg": "#182234",
    "explorer_border": "#334155",
    "explorer_hover": "#212D44",
    "explorer_icon": "#F8FAFC",
}

LIGHT_PALETTE = {
    "mode": "light",
    "bg_window": "#F8FAFC",
    "bg_sidebar": "#EEF2F6",
    "bg_glass": "#FFFFFF",
    "bg_glass_elevated": "#F1F5F9",
    "bg_table": "#FFFFFF",
    "bg_table_alt": "#F1F5F9",
    "bg_header": "#EEF2F6",
    "bg_menu": "#FFFFFF",
    "bg_track": "#E2E8F0",
    "bg_hover": "#E6ECF5",
    "bg_active": "#DDE5F0",
    "border_hairline": "#D5DCE6",
    "border_strong": "#AEB8C7",
    "border_selected": "#64748B",
    "text_primary": "#0A0F1D",
    "text_secondary": "#334155",
    "text_muted": "#4A5568",
    "primary_bg": "#0F172A",
    "primary_fg": "#F8FAFC",
    "primary_hover": "#1E293B",
    "icon_color": "#0A0F1D",
    "icon_inverted": "#F8FAFC",
    "accent": "#2563EB",
    "accent_alt": "#3B82F6",
    "motion_cyan": "#2563EB",
    "motion_blue": "#3B82F6",
    "tag_ice": "#2563EB",
    "tag_warn": "#92400E",
    "tag_risk": "#991B1B",
    "tag_ok": "#166534",
    "restore_bg": "#DCFCE7",
    "restore_bd": "#86EFAC",
    "restore_hover": "#BBF7D0",
    "move_bg": "#FEF3C7",
    "move_bd": "#FCD34D",
    "move_hover": "#FDE68A",
    "risk_bg": "#FEE2E2",
    "risk_bd": "#FCA5A5",
    "risk_hover": "#FECACA",
    "explorer_bg": "#F1F5F9",
    "explorer_border": "#AEB8C7",
    "explorer_hover": "#DDE5F0",
    "explorer_icon": "#0A0F1D",
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
        background-color: {p["bg_glass_elevated"]};
        border-bottom: 1px solid {p["border_hairline"]};
    }}

    QPushButton#ExplorerBtn {{
        background-color: transparent;
        border: 1px solid transparent;
        padding: 6px 10px;
        min-width: 34px;
        max-width: 36px;
    }}

    QPushButton#ExplorerBtn:hover {{
        background-color: {p["bg_hover"]};
        border: 1px solid transparent;
    }}

    QPushButton#BellBtn {{
        background-color: transparent;
        border: 1px solid transparent;
        color: {p["text_primary"]};
        padding: 5px 10px;
        font-family: "{MONO_FONT_FAMILY}", "IBM Plex Mono", monospace;
        font-size: 11px;
    }}

    QPushButton#BellBtn:hover {{
        background-color: {p["bg_hover"]};
        border: 1px solid transparent;
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
        border: 1px solid {p["border_strong"]};
        color: {p["text_primary"]};
    }}

    QPushButton#PrimaryAction {{
        background-color: {p["primary_bg"]};
        color: {p["primary_fg"]};
        border: none;
        padding: 8px 16px;
        font-size: 12px;
        font-weight: 700;
        letter-spacing: 0.2px;
    }}

    QPushButton#PrimaryAction:hover {{
        background-color: {p["primary_hover"]};
        border: none;
    }}

    QPushButton#PrimaryAction:disabled {{
        opacity: 0.45;
    }}

    /* Botones planos sin bordes ni acentos cian en reposo (estilo PDF Lector TRODAI). */
    QPushButton#GhostAction {{
        background-color: transparent;
        color: {p["text_primary"]};
        border: 1px solid transparent;
        padding: 6px 11px;
        font-size: 12px;
        font-weight: 500;
    }}

    QPushButton#GhostAction:hover {{
        background-color: {p["bg_hover"]};
        border: 1px solid transparent;
    }}

    QPushButton#GhostAction:pressed {{
        background-color: {p["bg_active"]};
    }}

    QPushButton#GhostAction[selected="true"] {{
        background-color: {p["bg_active"]};
        border: 1px solid {p["border_selected"]};
        font-weight: 700;
    }}

    /* Pestanas de modo planas sin bordes visibles en reposo y fondo neutro al activarse. */
    QPushButton#ModeTab {{
        background-color: transparent;
        color: {p["text_secondary"]};
        border: 1px solid transparent;
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
        border: 1px solid transparent;
        border-bottom: 2px solid {p["border_selected"]};
        font-weight: 700;
    }}

    /* Acciones especificas de cada pestana 100% solidas opacas (cero rgba). */
    QPushButton#RestoreAction, QPushButton#MoveAction, QPushButton#RiskAction {{
        padding: 7px 12px;
        font-size: 12px;
        font-weight: 700;
    }}

    QPushButton#RestoreAction {{
        background-color: {p["restore_bg"]};
        color: {p["tag_ok"]};
        border: 1px solid {p["restore_bd"]};
    }}

    QPushButton#RestoreAction:hover {{
        background-color: {p["restore_hover"]};
    }}

    QPushButton#MoveAction {{
        background-color: {p["move_bg"]};
        color: {p["tag_warn"]};
        border: 1px solid {p["move_bd"]};
    }}

    QPushButton#MoveAction:hover {{
        background-color: {p["move_hover"]};
    }}

    QPushButton#RiskAction {{
        background-color: {p["risk_bg"]};
        color: {p["tag_risk"]};
        border: 1px solid {p["risk_bd"]};
    }}

    QPushButton#RiskAction:hover {{
        background-color: {p["risk_hover"]};
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
        border-color: {p["border_selected"]};
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

    QHeaderView::section:hover {{
        background-color: {p["bg_hover"]};
        color: {p["text_primary"]};
        border-right: 1px solid {p["border_selected"]};
    }}

    QProgressBar {{
        background-color: {p["border_hairline"]};
        border: none;
        height: 3px;
        text-align: center;
    }}

    QProgressBar::chunk {{
        background-color: {p["border_selected"]};
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
        background-color: {p["bg_active"]};
        border-color: {p["text_primary"]};
    }}

    QCheckBox::indicator:indeterminate {{
        background-color: {p["border_strong"]};
        border-color: {p["border_selected"]};
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

    QScrollBar:horizontal {{
        background: transparent;
        height: 9px;
        margin: 0px;
    }}

    QScrollBar::handle:horizontal {{
        background: {p["border_strong"]};
        min-width: 28px;
    }}

    QScrollBar::handle:horizontal:hover, QScrollBar::handle:vertical:hover {{
        background: {p["border_selected"]};
    }}

    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {{
        width: 0px;
    }}

    QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal,
    QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical {{
        background: transparent;
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

    /* v0.6.9: las areas desplazables usaban el fondo blanco nativo (Centro de notificaciones en
       modo oscuro). Fondo transparente: hereda el panel del tema. */
    QScrollArea, QScrollArea > QWidget#qt_scrollarea_viewport {{
        background: transparent;
        border: none;
    }}

    QTabWidget::pane {{
        border: 1px solid {p["border_hairline"]};
        background-color: transparent;
    }}

    /* v0.6.5: con setDocumentMode(True) Windows pinta una base blanca nativa detras de las
       pestanas; en modo oscuro el texto claro quedaba sobre blanco. Base apagada + fondo propio. */
    QTabBar {{
        background-color: transparent;
        qproperty-drawBase: 0;
    }}

    QTabWidget::tab-bar {{
        background-color: transparent;
    }}

    QTabBar::tab {{
        background-color: {p["bg_glass"]};
        color: {p["text_secondary"]};
        border: 1px solid {p["border_hairline"]};
        padding: 6px 12px;
        font-family: "{MONO_FONT_FAMILY}", "IBM Plex Mono", monospace;
        font-size: 11px;
        margin-right: 4px;
    }}

    QTabBar::tab:hover:!selected {{
        background-color: {p["bg_hover"]};
        color: {p["text_primary"]};
    }}

    QTabBar::tab:selected {{
        background-color: {p["bg_active"]};
        color: {p["text_primary"]};
        border-bottom: 2px solid {p["border_selected"]};
        font-weight: 700;
    }}

    QToolTip {{
        background-color: {p["bg_menu"]};
        color: {p["text_primary"]};
        border: 1px solid {p["border_strong"]};
        border-radius: 0px;
        padding: 8px 10px;
        font-family: "{UI_FONT_FAMILY}", "Instrument Sans", "Segoe UI", sans-serif;
        font-size: 12px;
    }}
    """
