"""Minimalist TRODAI System Tray integration (octagonal high-contrast icon, active mode checkmarks, clickable toasts)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import QByteArray, QPointF, Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from .. import get_base_dir
from ..core.win32_bridge import is_windows_taskbar_light_theme


_THERMAL_SHORT_LABELS: dict[str, str] = {
    "cool": "Frio",
    "balanced": "Equilibrado",
    "ai_local": "IA Maxima",
}

_FALLBACK_FAVICON_SVG = (
    '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 100 100">'
    '<g fill="none" stroke="currentColor" stroke-width="7" stroke-linecap="square" stroke-linejoin="miter" stroke-miterlimit="4">'
    '<polygon points="50,10 78,20 90,40 80,46 80,64 50,90 20,64 20,46 10,40 22,20"/>'
    '<polygon points="40,56 60,56 66,72 34,72"/>'
    '<path d="M30 42 L42 42"/><path d="M58 42 L70 42"/>'
    "</g></svg>"
)


def _favicon_svg_template() -> str:
    svg_path = get_base_dir() / "assets" / "icons" / "trodai_favicon.svg"
    if svg_path.exists():
        return svg_path.read_text(encoding="utf-8")
    return _FALLBACK_FAVICON_SVG


def build_high_contrast_tray_icon(light_taskbar: bool | None = None) -> QIcon:
    """Render crisp multi-size TRODAI Hexa-Vault octagonal badge visible on Light & Dark Windows 11 trays."""
    is_light = is_windows_taskbar_light_theme() if light_taskbar is None else light_taskbar
    icon = QIcon()

    bg_color = QColor("#0A0F1D")
    rim_color = QColor("#3B82F6") if is_light else QColor("#60A5FA")
    stroke_color = "#0EA5E9" if not is_light else "#38BDF8"
    svg_data = _favicon_svg_template().replace("currentColor", stroke_color).encode("utf-8")
    renderer = QSvgRenderer(QByteArray(svg_data))

    for sz in (16, 20, 24, 32):
        pm = QPixmap(sz, sz)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # Solid high-contrast TRODAI Obsidian Navy octagonal container
        c = max(2.0, sz * 0.16)
        s = float(sz - 1)
        oct_pts = QPolygonF(
            [
                QPointF(c, 0),
                QPointF(s - c, 0),
                QPointF(s, c),
                QPointF(s, s - c),
                QPointF(s - c, s),
                QPointF(c, s),
                QPointF(0, s - c),
                QPointF(0, c),
            ]
        )
        painter.setPen(QPen(rim_color, max(1, sz // 16)))
        painter.setBrush(bg_color)
        painter.drawPolygon(oct_pts)

        # Inner Hexa-Vault Sentinel simplified marks
        pad = max(2.0, sz * 0.15)
        renderer.render(painter, oct_pts.boundingRect().adjusted(pad, pad, -pad, -pad))
        painter.end()
        icon.addPixmap(pm)
    return icon


class WinOptiTray(QSystemTrayIcon):
    """High-contrast TRODAI tray icon showing active modes, updates, and clickable notifications."""

    def __init__(
        self,
        parent: QWidget,
        on_show: Callable[[], None],
        on_boost: Callable[[], None],
        on_thermal: Callable[[str], None],
        on_quit: Callable[[], None],
        on_toggle_sre: Callable[[bool], None] | None = None,
        on_toggle_theme: Callable[[], None] | None = None,
        on_open_updates: Callable[[], None] | None = None,
        initial_thermal: str = "balanced",
        initial_sre: bool = True,
        initial_theme: str = "dark",
    ) -> None:
        super().__init__(build_high_contrast_tray_icon(), parent)
        self._last_taskbar_light: bool | None = None
        self._on_show = on_show
        self._on_open_updates = on_open_updates
        self._last_toast_kind = "general"

        menu = QMenu()
        self.status_action = QAction("Estado: En reposo", menu)
        self.status_action.setEnabled(False)
        menu.addAction(self.status_action)
        menu.addSeparator()

        act_open = QAction("Abrir WinOptiAI", menu)
        act_open.triggered.connect(on_show)
        menu.addAction(act_open)

        self.update_action = QAction("Actualizacion disponible", menu)
        self.update_action.setVisible(False)
        if on_open_updates is not None:
            self.update_action.triggered.connect(on_open_updates)
        menu.addAction(self.update_action)

        act_boost = QAction("Ejecutar AI Boost (RAM + EcoQoS)", menu)
        act_boost.triggered.connect(on_boost)
        menu.addAction(act_boost)

        menu.addSeparator()
        self.therm_menu = menu.addMenu("Perfil Termico")
        self._thermal_group = QActionGroup(self.therm_menu)
        self._thermal_group.setExclusive(True)
        self._thermal_actions: dict[str, QAction] = {}
        for key, label in (
            ("cool", "Frio / Silencioso"),
            ("balanced", "Equilibrado Inteligente"),
            ("ai_local", "IA Local Maxima"),
        ):
            act = QAction(label, self.therm_menu)
            act.setCheckable(True)
            act.triggered.connect(lambda _=False, k=key: on_thermal(k))
            self._thermal_group.addAction(act)
            self.therm_menu.addAction(act)
            self._thermal_actions[key] = act

        self.sre_action = QAction("Guardia SRE Automatico", menu)
        self.sre_action.setCheckable(True)
        self.sre_action.setChecked(initial_sre)
        if on_toggle_sre is not None:
            self.sre_action.toggled.connect(lambda checked: on_toggle_sre(bool(checked)))
        else:
            self.sre_action.setEnabled(False)
        menu.addAction(self.sre_action)

        self.theme_action = QAction("Tema Claro (Crisp White)", menu)
        self.theme_action.setCheckable(True)
        self.theme_action.setChecked(initial_theme == "light")
        if on_toggle_theme is not None:
            self.theme_action.triggered.connect(lambda _=False: on_toggle_theme())
        else:
            self.theme_action.setEnabled(False)
        menu.addAction(self.theme_action)

        menu.addSeparator()
        act_exit = QAction("Salir de WinOptiAI", menu)
        act_exit.triggered.connect(on_quit)
        menu.addAction(act_exit)

        menu.aboutToShow.connect(self.refresh_theme_icon)
        self._menu = menu
        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self.messageClicked.connect(self._on_message_clicked)

        self.sync_state(
            thermal_key=initial_thermal,
            sre_enabled=initial_sre,
            theme_mode=initial_theme,
            task_summary="",
        )

    def show_toast(self, title: str, detail: str, kind: str = "general", msecs: int = 8000) -> None:
        """Display a Windows toast remembering intent so clicking it jumps to the right action."""
        self._last_toast_kind = kind
        self.showMessage(title, detail, QSystemTrayIcon.MessageIcon.Information, msecs)

    def refresh_theme_icon(self) -> None:
        is_light = is_windows_taskbar_light_theme()
        if self._last_taskbar_light != is_light:
            self._last_taskbar_light = is_light
            self.setIcon(build_high_contrast_tray_icon(is_light))

    def sync_state(
        self,
        thermal_key: str | None = None,
        sre_enabled: bool | None = None,
        theme_mode: str | None = None,
        task_summary: str | None = None,
        available_update: str | None = None,
    ) -> None:
        """Keep tray checkmarks, active mode titles, update notice, and tooltip synchronized with MainWindow."""
        if thermal_key is not None:
            act = self._thermal_actions.get(thermal_key)
            if act is not None and not act.isChecked():
                act.setChecked(True)
            short_lbl = _THERMAL_SHORT_LABELS.get(thermal_key, thermal_key)
            self.therm_menu.setTitle(f"Perfil Termico: {short_lbl}")

        if sre_enabled is not None:
            self.sre_action.blockSignals(True)
            self.sre_action.setChecked(bool(sre_enabled))
            self.sre_action.blockSignals(False)

        if theme_mode is not None:
            self.theme_action.blockSignals(True)
            self.theme_action.setChecked(theme_mode == "light")
            self.theme_action.blockSignals(False)

        if task_summary is not None:
            clean_task = task_summary.strip()
            self.status_action.setText(
                f"En curso: {clean_task}" if clean_task else "Estado: En reposo"
            )

        if available_update is not None:
            tag_clean = available_update.strip()
            if tag_clean:
                self.update_action.setText(f"Actualizar a {tag_clean} disponible")
                self.update_action.setVisible(True)
            else:
                self.update_action.setVisible(False)

        active_therm = next(
            (k for k, a in self._thermal_actions.items() if a.isChecked()),
            "balanced",
        )
        t_lbl = _THERMAL_SHORT_LABELS.get(active_therm, active_therm)
        sre_lbl = "SRE ON" if self.sre_action.isChecked() else "SRE OFF"
        # v0.6.1: el propietario pidio un tooltip corto (solo el nombre); el estado va en el menu.
        self.setToolTip("WinOptiAI")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._on_show()

    def _on_message_clicked(self) -> None:
        if self._last_toast_kind == "update" and self._on_open_updates is not None:
            self._on_open_updates()
            return
        self._on_show()
