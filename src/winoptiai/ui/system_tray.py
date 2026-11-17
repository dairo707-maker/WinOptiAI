"""Minimalist System Tray integration (high-contrast adaptive icon & live mode checkmarks)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QActionGroup, QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from ..core.win32_bridge import is_windows_taskbar_light_theme


_THERMAL_SHORT_LABELS: dict[str, str] = {
    "cool": "Frio",
    "balanced": "Equilibrado",
    "ai_local": "IA Maxima",
}


def build_high_contrast_tray_icon(light_taskbar: bool | None = None) -> QIcon:
    """Render crisp multi-size 0px geometric tray badge visible on both Light & Dark Windows 11 trays."""
    is_light = is_windows_taskbar_light_theme() if light_taskbar is None else light_taskbar
    icon = QIcon()

    bg_color = QColor("#11161F") if is_light else QColor("#181E29")
    rim_color = QColor("#2C3848") if is_light else QColor("#D8E0EA")
    ink_color = QColor("#F8FAFC") if is_light else QColor("#F1F5F9")
    accent_color = QColor("#6E92B5") if is_light else QColor("#8EB3D6")

    for sz in (16, 20, 24, 32):
        pm = QPixmap(sz, sz)
        pm.fill(Qt.GlobalColor.transparent)
        painter = QPainter(pm)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, False)

        # Solid high-contrast architectural plate so frosted flyouts never wash out the icon
        painter.fillRect(0, 0, sz, sz, bg_color)
        rim_pen = QPen(rim_color, max(1, sz // 16))
        painter.setPen(rim_pen)
        painter.drawRect(0, 0, sz - 1, sz - 1)

        pad = max(2, round(sz * 0.19))
        stroke = max(1, round(sz * 0.09))
        pen = QPen(ink_color, stroke)
        painter.setPen(pen)
        outer_w = sz - (pad * 2) - 1
        painter.drawRect(pad, pad, outer_w, outer_w)

        split_x = round(sz * 0.44)
        split_y = round(sz * 0.44)
        painter.drawLine(pad, split_y, sz - pad - 1, split_y)
        painter.drawLine(split_x, split_y, split_x, sz - pad - 1)

        # Crisp filled accent block in lower-right quadrant
        inner_off = max(2, round(sz * 0.09))
        ax = split_x + inner_off
        ay = split_y + inner_off
        aw = (sz - pad - inner_off) - ax
        ah = (sz - pad - inner_off) - ay
        if aw >= 2 and ah >= 2:
            painter.fillRect(ax, ay, aw, ah, accent_color)
        painter.end()
        icon.addPixmap(pm)
    return icon


class WinOptiTray(QSystemTrayIcon):
    """High-contrast tray icon showing active thermal/SRE/theme modes & quick controls."""

    def __init__(
        self,
        parent: QWidget,
        on_show: Callable[[], None],
        on_boost: Callable[[], None],
        on_thermal: Callable[[str], None],
        on_quit: Callable[[], None],
        on_toggle_sre: Callable[[bool], None] | None = None,
        on_toggle_theme: Callable[[], None] | None = None,
        initial_thermal: str = "balanced",
        initial_sre: bool = True,
        initial_theme: str = "dark",
    ) -> None:
        super().__init__(build_high_contrast_tray_icon(), parent)
        self._last_taskbar_light: bool | None = None
        self._on_show = on_show

        menu = QMenu()
        self.status_action = QAction("Estado: En reposo", menu)
        self.status_action.setEnabled(False)
        menu.addAction(self.status_action)
        menu.addSeparator()

        act_open = QAction("Abrir WinOptiAI", menu)
        act_open.triggered.connect(on_show)
        menu.addAction(act_open)

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

        self.theme_action = QAction("Tema Claro (Alabaster)", menu)
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

        self.sync_state(
            thermal_key=initial_thermal,
            sre_enabled=initial_sre,
            theme_mode=initial_theme,
            task_summary="",
        )

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
    ) -> None:
        """Keep tray checkmarks, active mode titles, and tooltip synchronized with MainWindow."""
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

        active_therm = next(
            (k for k, a in self._thermal_actions.items() if a.isChecked()),
            "balanced",
        )
        t_lbl = _THERMAL_SHORT_LABELS.get(active_therm, active_therm)
        sre_lbl = "SRE ON" if self.sre_action.isChecked() else "SRE OFF"
        self.setToolTip(f"WinOptiAI | Termica: {t_lbl} | {sre_lbl}")

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._on_show()
