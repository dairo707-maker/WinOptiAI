"""Modern Notification Bell, Live Task Controls (Pause/Save/Cancel), and Resumable Sessions Drawer."""

from __future__ import annotations

from typing import Callable

from PySide6.QtCore import Qt, QTimer
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
from ...core.task_control import SessionManager, TaskSessionRecord
from ..svg_icons import load_svg_icon
from ..theme import get_palette
from ..widgets import GlassPanel, StatusTag
from ..workers import AsyncTask


class NotificationsTasksDialog(QDialog):
    """0px drawer showing live concurrent tasks (Pause/Save/Cancel), saved sessions, and notifications."""

    def __init__(
        self,
        center: NotificationCenter,
        active_tasks_fn: Callable[[], list[AsyncTask]],
        on_jump_tab: Callable[[int], None],
        theme_mode: str = "dark",
        parent: QWidget | None = None,
        session_mgr: SessionManager | None = None,
        on_resume_session: Callable[[TaskSessionRecord], None] | None = None,
        on_sync_tasks: Callable[[], None] | None = None,
        on_open_diagnostics: Callable[[], None] | None = None,
    ) -> None:
        super().__init__(parent)
        self.center = center
        self.active_tasks_fn = active_tasks_fn
        self.on_jump_tab = on_jump_tab
        self.theme_mode = theme_mode
        self.session_mgr = session_mgr
        self.on_resume_session = on_resume_session
        self.on_sync_tasks = on_sync_tasks
        self.on_open_diagnostics = on_open_diagnostics

        self.setWindowTitle("Procesos Activos, Sesiones y Notificaciones")
        self.resize(610, 620)

        root = QVBoxLayout(self)
        root.setContentsMargins(18, 16, 18, 16)
        root.setSpacing(10)

        # Section 1: Live Concurrent Tasks + Controls
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

        # Section 2: Saved Resumable Sessions
        s_hdr = QHBoxLayout()
        s_lbl = QLabel("SESIONES GUARDADAS (RETOMAR DESPUES)")
        s_lbl.setObjectName("SectionLabel")
        s_hdr.addWidget(s_lbl)
        s_hdr.addStretch()
        self.sessions_tag = StatusTag("0 GUARDADAS", "neutral")
        s_hdr.addWidget(self.sessions_tag)
        root.addLayout(s_hdr)

        self.sessions_container = QVBoxLayout()
        self.sessions_container.setSpacing(6)
        self.sessions_host = GlassPanel()
        self.sessions_host.setLayout(self.sessions_container)
        root.addWidget(self.sessions_host)

        # Section 3: Persistent Notifications + Clear controls
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

        if on_open_diagnostics is not None:
            diag_btn = QPushButton("Diagnostico")
            diag_btn.setObjectName("GhostAction")
            diag_btn.setToolTip("Ver o copiar crash.log y cierres inesperados detectados")
            diag_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            diag_btn.clicked.connect(on_open_diagnostics)
            n_hdr.addWidget(diag_btn)

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
        # v0.5.1: nunca destruir de inmediato; ocultar y deleteLater para que un boton
        # hijo cuya senal sigue en la pila (clicked -> re-render) no sea liberado en C++.
        while layout.count():
            item = layout.takeAt(0)
            w = item.widget()
            if w is not None:
                w.hide()
                w.deleteLater()

    def _defer(self, fn: Callable[[], None]) -> None:
        """Run a re-render after the emitting child button's slot has fully unwound."""
        QTimer.singleShot(0, self, fn)

    def refresh(self) -> None:
        self._render_tasks()
        self._render_sessions()
        self._render_notifications()

    def _toggle_pause(self, task: AsyncTask) -> None:
        if task.controller.is_paused:
            task.controller.resume()
        else:
            task.controller.pause()
        self._defer(self._render_tasks)
        if self.on_sync_tasks is not None:
            self._defer(self.on_sync_tasks)

    def _save_and_pause(self, task: AsyncTask) -> None:
        task.controller.pause_and_save()
        if self.on_sync_tasks is not None:
            self._defer(self.on_sync_tasks)

    def _cancel_task(self, task: AsyncTask) -> None:
        task.controller.cancel()
        if self.on_sync_tasks is not None:
            self._defer(self.on_sync_tasks)

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
            rl.setSpacing(6)
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

            ctl = QHBoxLayout()
            ctl.setSpacing(6)
            ctl.addStretch()
            pause_btn = QPushButton("Reanudar" if task.controller.is_paused else "Pausar")
            pause_btn.setObjectName("GhostAction")
            pause_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            pause_btn.clicked.connect(lambda _=False, t=task: self._toggle_pause(t))
            ctl.addWidget(pause_btn)

            save_btn = QPushButton("Guardar Sesion")
            save_btn.setObjectName("GhostAction")
            save_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            save_btn.clicked.connect(lambda _=False, t=task: self._save_and_pause(t))
            ctl.addWidget(save_btn)

            cancel_btn = QPushButton("Cancelar")
            cancel_btn.setObjectName("GhostAction")
            cancel_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            cancel_btn.clicked.connect(lambda _=False, t=task: self._cancel_task(t))
            ctl.addWidget(cancel_btn)
            rl.addLayout(ctl)
            self.tasks_container.addWidget(row_w)

    def _render_sessions(self) -> None:
        self._clear_layout(self.sessions_container)
        sessions = self.session_mgr.list_sessions() if self.session_mgr else []
        self.sessions_tag.set_tone(f"{len(sessions)} GUARDADAS", "warn" if sessions else "neutral")
        self.sessions_host.setVisible(bool(sessions))
        if not sessions:
            return
        for rec in sessions:
            row = QWidget()
            rl = QHBoxLayout(row)
            rl.setContentsMargins(10, 6, 10, 6)
            rl.setSpacing(8)
            info = QLabel(
                f"{rec.title} — {rec.percent}% | {len(rec.pending_paths)} pendientes ({rec.created_at})"
            )
            info.setObjectName("MonoValue")
            rl.addWidget(info, stretch=1)

            res_btn = QPushButton("Reanudar")
            res_btn.setObjectName("PrimaryAction")
            res_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            res_btn.clicked.connect(lambda _=False, s=rec: self._resume_saved(s))
            rl.addWidget(res_btn)

            drop_btn = QPushButton("Descartar")
            drop_btn.setObjectName("GhostAction")
            drop_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            drop_btn.clicked.connect(lambda _=False, sid=rec.session_id: self._discard_saved(sid))
            rl.addWidget(drop_btn)
            self.sessions_container.addWidget(row)

    def _resume_saved(self, rec: TaskSessionRecord) -> None:
        if self.on_resume_session is not None:
            self.on_resume_session(rec)
            self._defer(self.refresh)

    def _discard_saved(self, sid: str) -> None:
        if self.session_mgr is not None:
            self.session_mgr.remove_session(sid)
        self._defer(self._render_sessions)
        if self.on_sync_tasks is not None:
            self._defer(self.on_sync_tasks)

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
        self._defer(self._render_notifications)

    def _mark_all_read(self) -> None:
        self.center.mark_all_read()
        self._defer(self._render_notifications)

    def _clear_all(self) -> None:
        self.center.clear_all()
        self._defer(self._render_notifications)
