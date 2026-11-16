"""Minimalist System Tray integration (SVG icon, quick actions, SRE alerts)."""

from __future__ import annotations

from typing import Callable

from PySide6.QtGui import QAction
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QWidget

from .svg_icons import load_svg_icon


class WinOptiTray(QSystemTrayIcon):
    """Lightweight tray icon offering 1-click AI Boost and thermal profile switches."""

    def __init__(
        self,
        parent: QWidget,
        on_show: Callable[[], None],
        on_boost: Callable[[], None],
        on_thermal: Callable[[str], None],
        on_quit: Callable[[], None],
    ) -> None:
        super().__init__(load_svg_icon("brand", color="#E2E7ED", size=18), parent)
        self.setToolTip("WinOptiAI - Almacenamiento, Procesos IA y Termica")

        menu = QMenu()
        act_open = QAction("Abrir WinOptiAI", menu)
        act_open.triggered.connect(on_show)
        menu.addAction(act_open)

        act_boost = QAction("Ejecutar AI Boost (RAM + EcoQoS)", menu)
        act_boost.triggered.connect(on_boost)
        menu.addAction(act_boost)

        menu.addSeparator()
        therm_menu = menu.addMenu("Perfil Termico")
        for key, label in (
            ("cool", "Frio / Silencioso"),
            ("balanced", "Equilibrado Inteligente"),
            ("ai_local", "IA Local Maxima"),
        ):
            act = QAction(label, therm_menu)
            act.triggered.connect(lambda _=False, k=key: on_thermal(k))
            therm_menu.addAction(act)

        menu.addSeparator()
        act_exit = QAction("Salir de WinOptiAI", menu)
        act_exit.triggered.connect(on_quit)
        menu.addAction(act_exit)

        self.setContextMenu(menu)
        self.activated.connect(self._on_activated)
        self._on_show = on_show

    def _on_activated(self, reason: QSystemTrayIcon.ActivationReason) -> None:
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._on_show()
