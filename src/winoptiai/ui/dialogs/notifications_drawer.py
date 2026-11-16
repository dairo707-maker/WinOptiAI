"""Modern Notification Bell & Concurrent Background Task Progress Dialog."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog,
    QHBoxLayout,
    QLabel,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from ...core.notifications import NotificationCenter
from ..svg_icons import load_svg_icon
from ..theme import get_palette
from ..widgets import GlassPanel, StatusTag
from ..workers import AsyncTask


class NotificationsTasksDialog(QDialog):
    """0px drawer showing live concurrent tasks (with % bars) and dismissible notifications."""

    def __init__(
        self,
        center: NotificationCenter,
        active_tasks_fn: Callable[[], list[AsyncTask]],
        on_jump_tab: Callable[[int], None],
        theme_mode: str = "dark",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.center = center
        self.active_tasks_fn = active_tasks_fn
        self.on_jump_tab = on_jump_tab
        self.theme_mode = theme_mode

        self.setWindowTitle("Procesos Activos y Notificaciones")
        self.resize(560, 560)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(12)

        # Section 1: Live Concurrent Tasks
        t_hdr = QHBoxLayout()
        t_lbl = QLabel("PROCESOS EN SEGUNDO PLANO")
        t_lbl.setObjectName("SectionLabel")
        t_hdr.addWidget(t_lbl)
        t_hdr.addStretch()
        self.tasks_count_tag = StatusTag("0 ACTIVOS", "neutral")
        t_hdr.addWidget(self.tasks_count_tag)
        root.addLayout(t_hdr)

        self.tasks_container = QVBoxLayout()
        self.tasks_container.setSpacing(6)
        tasks_host = GlassPanel()
        tasks_host.setLayout(self.tasks_container)
        root.addWidget(tasks_host)

        # Section 2: Persistent Notifications + Clear controls
        n_hdr = QHBoxLayout()
        n_lbl = QLabel("CENTRO DE NOTIFICACIONES")
        n_lbl.setObjectName("SectionLabel")
        n_hdr.addWidget(n_lbl)
        n_hdr.addStretch()

        mark_btn = QPushButton("Marcar leidas")
        mark_btn.setObjectName("GhostAction")
        mark_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        mark_btn.clicked.connect(self._mark_all_read)
        n_hdr.addWidget(mark_btn)

        clear_btn = QPushButton("Limpiar todas")
        clear_btn.setObjectName("GhostAction")
        clear_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        clear_btn.clicked.connect(self._clear_all)
        n_hdr.addWidget(clear_btn)
        root.addLayout(n_hdr)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        self.notif_list_widget = QWidget()
        self.notif_layout = QVBoxLayout(self.notif_list_widget)
        self.notif_layout.setContentsMargins(0, 0, 0, 0)
        self.notif_layout.setSpacing(6)
        scroll.setWidget(self.notif_list_widget)
        root.addWidget(scroll, stretch=1)

        self.refresh()

    def _clear_layout(self, layout: QVBoxLayout) -> None:
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()

    def refresh(self) -> None:
        self._render_tasks()
        self._render_notifications()

    def _render_tasks(self) -> None:
        self._clear_layout(self.tasks_container)
        tasks = self.active_tasks_fn()
        self.tasks_count_tag.set_tone(
            f"{len(tasks)} ACTIVOS", "active" if tasks else "neutral"
        )
        if not tasks:
            empty = QLabel("Sin procesos pesados en ejecucion en este momento.")
            empty.setObjectName("PageSubtitle")
            empty.setContentsMargins(10, 8, 10, 8)
            self.tasks_container.addWidget(empty)
            return

        for task in tasks:
            row_w = QWidget()
            rl = QVBoxLayout(row_w)
            rl.setContentsMargins(10, 8, 10, 8)
            rl.setSpacing(4)
            top = QHBoxLayout()
            title = QLabel(f"{task.title} ({task.started_at})")
            title.setStyleSheet("font-size: 12px; font-weight: 600;")
            top.addWidget(title)
            top.addStretch()
            eta = task.eta_label()
            eta_part = f" ({eta})" if eta else ""
            pct_lbl = QLabel(f"{task.percent}%{eta_part}  |  {task.stage}")
            pct_lbl.setObjectName("MonoValue")
            top.addWidget(pct_lbl)
            rl.addLayout(top)

            bar = QProgressBar()
            bar.setRange(0, 100)
            bar.setValue(task.percent)
            bar.setTextVisible(False)
            rl.addWidget(bar)
            self.tasks_container.addWidget(row_w)

    def _render_notifications(self) -> None:
        self._clear_layout(self.notif_layout)
        items = self.center.list_items()
        pal = get_palette(self.theme_mode)

        if not items:
            empty = QLabel("No hay notificaciones registradas.")
            empty.setObjectName("PageSubtitle")
            self.notif_layout.addWidget(empty)
            self.notif_layout.addStretch()
            return

        tone_map = {
            "COMPLETADO": "ok",
            "SUGERENCIA": "active",
            "AVISO": "warn",
            "ERROR": "risk",
        }
        for item in items:
            card = GlassPanel(elevated=(not item.read))
            cl = QVBoxLayout(card)
            cl.setContentsMargins(12, 10, 12, 10)
            cl.setSpacing(5)

            top = QHBoxLayout()
            top.setSpacing(8)
            top.addWidget(StatusTag(item.kind, tone_map.get(item.kind, "neutral")))
            title = QLabel(item.title)
            title.setStyleSheet("font-size: 12px; font-weight: 600;")
            top.addWidget(title)
            top.addStretch()
            ts = QLabel(item.timestamp[11:])
            ts.setObjectName("PageSubtitle")
            top.addWidget(ts)

            if item.action_tab is not None:
                go_btn = QPushButton("Abrir")
                go_btn.setObjectName("GhostAction")
                go_btn.clicked.connect(lambda _=False, tab=item.action_tab: self._jump(tab))
                top.addWidget(go_btn)

            del_btn = QPushButton()
            del_btn.setObjectName("GhostAction")
            del_btn.setIcon(load_svg_icon("close", color=pal["icon_color"], size=11))
            del_btn.setToolTip("Eliminar esta notificacion")
            del_btn.setFixedWidth(26)
            del_btn.clicked.connect(lambda _=False, nid=item.notif_id: self._delete_one(nid))
            top.addWidget(del_btn)
            cl.addLayout(top)

            detail = QLabel(item.detail)
            detail.setObjectName("PageSubtitle")
            detail.setWordWrap(True)
            cl.addWidget(detail)
            self.notif_layout.addWidget(card)

        self.notif_layout.addStretch()

    def _jump(self, tab_idx: int) -> None:
        self.on_jump_tab(tab_idx)
        self.close()

    def _delete_one(self, notif_id: str) -> None:
        self.center.remove(notif_id)
        self._render_notifications()

    def _mark_all_read(self) -> None:
        self.center.mark_all_read()
        self._render_notifications()

    def _clear_all(self) -> None:
        self.center.clear_all()
        self._render_notifications()
