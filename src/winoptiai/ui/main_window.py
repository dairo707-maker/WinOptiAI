"""Main Obsidian/Alabaster Acrylic window with Top Utility Bar, Bell Drawer, and Concurrent Hub."""

from __future__ import annotations

from datetime import datetime
import os
import sys
import time

import psutil
from PySide6.QtCore import Qt, QThreadPool, QTimer, Signal
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..ai_optimizer.process_manager import (
    detect_orphan_ai_workers,
    get_memory_snapshot,
    run_ai_boost,
)
from ..core.crash_guard import CrashGuard
from ..core.help_catalog import TOOLTIPS
from ..core.i18n import tr
from ..core.metrics_history import MetricsHistory, MinuteAggregator
from ..core.notifications import NotificationCenter, PeriodicAdvisor
from ..core.onboarding_check import QuickCheckReport
from ..core.safety_guard import PreOpBackupManager, QuarantineVault
from ..core.sre_policy import SREPolicyEngine
from ..core.task_control import SessionManager, TaskSessionRecord, new_session_id
from ..core.telemetry import PdhTelemetryReader
from ..core.updater import ReleaseInfo, check_for_updates
from ..core.win32_bridge import (
    apply_window_theme,
    is_user_admin,
    run_elevated_command,
    running_tracked_children,
    terminate_app_child_processes,
)
from ..storage.junk_scanner import resume_junk_session, scan_junk_targets
from ..thermal_bios.thermal_controller import THERMAL_PROFILES, apply_thermal_profile
from .dialogs.about_updater_dialog import AboutUpdaterDialog
from ..core.crash_reporter import KIND_CRASH, KIND_ERROR
from .dialogs.crash_report_dialog import CrashReportDialog
from .dialogs.crash_send_dialog import CrashSendDialog
from .dialogs.notifications_drawer import NotificationsTasksDialog
from .dialogs.tour_dialog import QuickTourDialog
from .svg_icons import load_svg_icon, load_svg_pixmap
from .system_tray import WinOptiTray
from .theme import build_obsidian_qss, get_palette
from .views.overview_view import OverviewView
from .views.processes_view import ProcessesView
from .views.storage_view import StorageView
from .views.thermal_bios_view import ThermalBiosView
from .widgets import AdaptiveButton, NotebookCanvas, StatusTag
from .workers import AsyncTask


def _task_pill_variants(title: str, percent: int, eta_part: str, extra: str) -> list[str]:
    """v0.5.6: textos del indicador de tareas de mas largo a mas corto (nunca se recorta)."""
    short_title = title.split("(")[0].strip() or title
    first_word = short_title.split()[0] if short_title.split() else short_title
    return [
        f"{title}: {percent}%{eta_part}{extra}",
        f"{short_title} {percent}%{eta_part}{extra}",
        f"{short_title} {percent}%{extra}",
        f"{first_word} {percent}%{extra}",
        f"{percent}%{extra}",
    ]


SHUTDOWN_WAIT_S = 15.0  # v0.5.9: espera maxima para que las tareas canceladas guarden lo avanzado
CRASH_RESTART_ARG = "--crash-restart"
ELEVATED_RELAUNCH_ARG = "--elevated-relaunch"
MAX_ERROR_PROMPTS_PER_SESSION = 3
MAX_CONCURRENT_TASKS = 4
MIN_RAM_FOR_NEW_TASK_GB = 1.0


class MainWindow(QMainWindow):
    """Primary desktop shell with RAM-aware concurrent jobs, Bell drawer, and periodic advisor."""

    # v0.5.3: excepciones no controladas (cualquier hilo) -> aviso de envio en el hilo GUI.
    unhandled_error = Signal(str, str, str)

    def __init__(self, crash_guard: CrashGuard | None = None, auto_restarted: bool = False) -> None:
        super().__init__()
        self.crash_guard = crash_guard
        self.auto_restarted = auto_restarted
        self._crash_dialog: CrashSendDialog | None = None
        self._tour_dialog: QuickTourDialog | None = None
        self._available_update: ReleaseInfo | None = None
        self._checking_updates = False
        self._reported_error_keys: set[str] = set()
        self.unhandled_error.connect(self._on_unhandled_error, Qt.ConnectionType.QueuedConnection)
        if crash_guard is not None:
            crash_guard.add_unhandled_listener(lambda origin, et, text: self.unhandled_error.emit(origin, et, text))
        self.setWindowTitle(f"WinOptiAI {__version__}")
        self.resize(1200, 760)
        self.setMinimumSize(980, 650)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(max(4, self.pool.maxThreadCount()))
        self._active_workers: list[AsyncTask] = []
        # v0.5.1: workers finalizados se retienen hasta el siguiente ciclo del event loop para
        # que su QObject de senales no se libere mientras su propia emision sigue en la pila.
        self._retired_workers: list[AsyncTask] = []
        self._notif_dialog: NotificationsTasksDialog | None = None

        self.vault = QuarantineVault()
        self.backup_mgr = PreOpBackupManager()
        self.policy = SREPolicyEngine()
        self.notif_center = NotificationCenter()
        self.session_mgr = SessionManager()
        self.advisor = PeriodicAdvisor(cooldown_seconds=7200)
        self.telemetry_reader = PdhTelemetryReader()
        # v0.5.8: historial local acotado (1 punto/min, 7 dias) en metrics.sqlite.
        self.metrics_history = MetricsHistory(self.policy.app_dir)
        self._minute_agg = MinuteAggregator()
        self._disk_free_gb = 0.0
        self._disk_total_gb = 0.0
        self._force_quit = False

        lang = self.policy.config.language
        theme_mode = self.policy.config.theme_mode
        pal = get_palette(theme_mode)

        self.root_canvas = NotebookCanvas(theme_mode=theme_mode)
        self.setCentralWidget(self.root_canvas)

        main_layout = QHBoxLayout(self.root_canvas)
        main_layout.setContentsMargins(0, 0, 0, 0)
        main_layout.setSpacing(0)

        # Sidebar
        sidebar = QWidget()
        sidebar.setObjectName("Sidebar")
        sidebar.setFixedWidth(248)  # v0.5.6: "Acerca de y Actualizaciones" completo
        sb_layout = QVBoxLayout(sidebar)
        sb_layout.setContentsMargins(0, 0, 0, 0)
        sb_layout.setSpacing(0)

        brand_box = QWidget()
        brand_layout = QHBoxLayout(brand_box)
        brand_layout.setContentsMargins(16, 18, 16, 18)
        brand_layout.setSpacing(10)
        self.brand_icon = QLabel()
        self.brand_icon.setPixmap(load_svg_pixmap("brand", color=pal["icon_color"], size=18))
        brand_layout.addWidget(self.brand_icon)

        brand_title = QLabel("WinOptiAI")
        brand_title.setStyleSheet("font-size: 14px; font-weight: 600; letter-spacing: 0.2px;")
        brand_layout.addWidget(brand_title)
        brand_layout.addStretch()
        brand_layout.addWidget(StatusTag(f"v{__version__}", "neutral"))
        sb_layout.addWidget(brand_box)

        self.nav_buttons: list[QPushButton] = []
        self._nav_spec = [
            ("overview", "nav_overview"),
            ("storage", "nav_storage"),
            ("process", "nav_processes"),
            ("thermal", "nav_thermal"),
        ]
        for idx, (icon_name, tr_key) in enumerate(self._nav_spec):
            btn = QPushButton(f"  {tr(tr_key, lang)}")
            btn.setObjectName("NavButton")
            btn.setIcon(load_svg_icon(icon_name, color=pal["icon_color"], size=15))
            btn.setCursor(Qt.CursorShape.PointingHandCursor)
            btn.clicked.connect(lambda _=False, i=idx: self._switch_tab(i))
            self.nav_buttons.append(btn)
            sb_layout.addWidget(btn)

        sb_layout.addStretch()

        # Quiet footer: Theme toggle, Language selector, About & Updates, Status
        footer = QWidget()
        f_layout = QVBoxLayout(footer)
        f_layout.setContentsMargins(14, 10, 14, 14)
        f_layout.setSpacing(8)

        ctl_row = QHBoxLayout()
        ctl_row.setSpacing(6)
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("GhostAction")
        self.theme_btn.setFixedWidth(36)
        self._refresh_theme_button_icon(theme_mode, pal["icon_color"])
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.clicked.connect(self._toggle_theme)
        ctl_row.addWidget(self.theme_btn)

        self.lang_combo = QComboBox()
        self.lang_combo.addItem("ES", "es")
        self.lang_combo.addItem("EN", "en")
        self.lang_combo.addItem("PT", "pt")
        idx_lang = self.lang_combo.findData(lang)
        if idx_lang >= 0:
            self.lang_combo.setCurrentIndex(idx_lang)
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        self.lang_combo.setToolTip(TOOLTIPS["lang_combo"])
        ctl_row.addWidget(self.lang_combo, stretch=1)
        f_layout.addLayout(ctl_row)

        self.tour_btn = QPushButton(f" {tr('btn_tour', lang)}")
        self.tour_btn.setObjectName("GhostAction")
        self.tour_btn.setIcon(load_svg_icon("overview", color=pal["icon_color"], size=13))
        self.tour_btn.setToolTip(TOOLTIPS["btn_tour"])
        self.tour_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.tour_btn.clicked.connect(self._open_tour_dialog)
        f_layout.addWidget(self.tour_btn)

        self.about_btn = QPushButton(f" {tr('btn_about', lang)}")
        self.about_btn.setObjectName("GhostAction")
        self.about_btn.setIcon(load_svg_icon("shield", color=pal["icon_color"], size=13))
        self.about_btn.setToolTip(TOOLTIPS["btn_about"])
        self.about_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.about_btn.clicked.connect(self._open_about_dialog)
        f_layout.addWidget(self.about_btn)

        self.status_lbl = QLabel(tr("status_ready", lang))
        self.status_lbl.setObjectName("PageSubtitle")
        self.status_lbl.setWordWrap(True)
        f_layout.addWidget(self.status_lbl)
        sb_layout.addWidget(footer)

        main_layout.addWidget(sidebar)

        # Right column: Top Utility Bar (Tasks Progress % + Admin UAC + Bell) + Stacked Views
        right_col = QWidget()
        rc_layout = QVBoxLayout(right_col)
        rc_layout.setContentsMargins(0, 0, 0, 0)
        rc_layout.setSpacing(0)

        top_bar = QWidget()
        top_bar.setObjectName("TopBar")
        top_bar.setFixedHeight(42)
        tb_layout = QHBoxLayout(top_bar)
        tb_layout.setContentsMargins(24, 6, 24, 6)
        tb_layout.setSpacing(10)

        self.task_pill_btn = AdaptiveButton("Sin procesos en segundo plano")
        self.task_pill_btn.setObjectName("GhostAction")
        self.task_pill_btn.setToolTip(TOOLTIPS["task_pill"])
        self.task_pill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.task_pill_btn.clicked.connect(self._open_notifications_drawer)
        tb_layout.addWidget(self.task_pill_btn)

        self.pause_top_btn = AdaptiveButton("Pausar")
        self.pause_top_btn.setObjectName("GhostAction")
        self.pause_top_btn.setToolTip(TOOLTIPS["pause_top"])
        self.pause_top_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.pause_top_btn.clicked.connect(self._toggle_lead_pause)
        self.pause_top_btn.setVisible(False)
        tb_layout.addWidget(self.pause_top_btn)

        self.save_pause_top_btn = AdaptiveButton("Guardar Pausa")
        self.save_pause_top_btn.set_variants(["Guardar Pausa", "Guardar"])
        self.save_pause_top_btn.setObjectName("GhostAction")
        self.save_pause_top_btn.setToolTip(TOOLTIPS["save_pause_top"])
        self.save_pause_top_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.save_pause_top_btn.clicked.connect(self._save_and_pause_lead)
        self.save_pause_top_btn.setVisible(False)
        tb_layout.addWidget(self.save_pause_top_btn)

        self.cancel_top_btn = AdaptiveButton("Cancelar")
        self.cancel_top_btn.setObjectName("GhostAction")
        self.cancel_top_btn.setToolTip(TOOLTIPS["cancel_top"])
        self.cancel_top_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.cancel_top_btn.clicked.connect(self._cancel_lead_task)
        self.cancel_top_btn.setVisible(False)
        tb_layout.addWidget(self.cancel_top_btn)

        self.resume_session_btn = AdaptiveButton("Retomar Sesion")
        self.resume_session_btn.setObjectName("PrimaryAction")
        self.resume_session_btn.setToolTip(TOOLTIPS["resume_session"])
        self.resume_session_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.resume_session_btn.clicked.connect(self._open_notifications_drawer)
        self.resume_session_btn.setVisible(False)
        tb_layout.addWidget(self.resume_session_btn)
        tb_layout.addStretch()

        is_admin = is_user_admin()
        self.admin_tag = StatusTag("ADMIN UAC" if is_admin else "MODO ESTANDAR", "ok" if is_admin else "neutral")
        tb_layout.addWidget(self.admin_tag)

        if not is_admin:
            self.uac_btn = AdaptiveButton("Elevar Admin (UAC)")
            self.uac_btn.set_variants(["Elevar Admin (UAC)", "Elevar Admin", "Admin"])
            self.uac_btn.setObjectName("GhostAction")
            self.uac_btn.setToolTip(TOOLTIPS["uac_btn"])
            self.uac_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.uac_btn.clicked.connect(self._request_admin_relaunch)
            tb_layout.addWidget(self.uac_btn)

        self.bell_btn = QPushButton(" 0")
        self.bell_btn.setObjectName("BellBtn")
        self.bell_btn.setIcon(load_svg_icon("bell", color=pal["icon_color"], size=15))
        self.bell_btn.setToolTip(TOOLTIPS["bell_btn"])
        self.bell_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bell_btn.clicked.connect(self._open_notifications_drawer)
        tb_layout.addWidget(self.bell_btn)
        rc_layout.addWidget(top_bar)

        # Stacked Views
        self.stack = QStackedWidget()
        self.overview_view = OverviewView(lang=lang)
        self.overview_view.trigger_ai_boost.connect(lambda: self._execute_ai_boost("usuario"))
        self.overview_view.attach_metrics(self.metrics_history, lambda: self.policy.config.ram_threshold_gb)
        self.storage_view = StorageView(
            self.vault, self.backup_mgr, self.policy, self._run_async, self._set_status, lang=lang
        )
        self.processes_view = ProcessesView(
            self.policy,
            self._run_async,
            lambda: self._execute_ai_boost("usuario"),
            self._set_status,
            lang=lang,
        )
        self.thermal_view = ThermalBiosView(
            self.policy,
            self.backup_mgr,
            self._run_async,
            self._set_status,
            self._on_elevated_temps,
            lang=lang,
        )
        self.thermal_view.audit_log_updated.connect(self._on_thermal_audit_updated)

        self.stack.addWidget(self.overview_view)
        self.stack.addWidget(self.storage_view)
        self.stack.addWidget(self.processes_view)
        self.stack.addWidget(self.thermal_view)
        rc_layout.addWidget(self.stack, stretch=1)
        main_layout.addWidget(right_col, stretch=1)

        # System Tray (must exist before _apply_ui_appearance syncs tray state)
        self.tray = WinOptiTray(
            self,
            on_show=self._restore_from_tray,
            on_boost=lambda: self._execute_ai_boost("usuario"),
            on_thermal=self._tray_thermal,
            on_quit=self._quit_app,
            on_toggle_sre=self._tray_toggle_sre,
            on_toggle_theme=self._toggle_theme,
            on_open_updates=self._open_about_from_tray,
            initial_thermal=self.policy.config.active_thermal_profile,
            initial_sre=self.policy.config.auto_ram_relief_enabled,
            initial_theme=self.policy.config.theme_mode,
        )
        self.tray.show()

        # Apply active palette icons across all views immediately on first frame
        self._apply_ui_appearance()

        self._switch_tab(0)
        self._refresh_bell_badge()

        # Live telemetry timer
        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.timeout.connect(self._sample_telemetry)
        self.telemetry_timer.start(2000)

        # Lightweight 1s ETA refresh timer active only while background tasks run
        self.task_eta_timer = QTimer(self)
        self.task_eta_timer.timeout.connect(self._sync_active_task_indicators)
        self.task_eta_timer.setInterval(1000)

        # Low-noise periodic optimization advisor (every 15 minutes)
        self.advisor_timer = QTimer(self)
        self.advisor_timer.timeout.connect(self._run_periodic_advisor)
        self.advisor_timer.start(900_000)

        # v0.5.13: automatic update check every 12 hours while open or in tray
        self.update_check_timer = QTimer(self)
        self.update_check_timer.timeout.connect(self._check_updates_background)
        self.update_check_timer.start(43_200_000)

        # v0.5.1: latido del marcador de sesion (solo si el crash guard esta activo)
        self.heartbeat_timer = QTimer(self)
        if self.crash_guard is not None:
            self.heartbeat_timer.timeout.connect(self.crash_guard.heartbeat)
            self.heartbeat_timer.start(60_000)
            # v0.5.3: pulso de 1 s del hilo GUI para el vigilante de bloqueos.
            self.ui_tick_timer = QTimer(self)
            self.ui_tick_timer.timeout.connect(self.crash_guard.ui_tick)
            self.ui_tick_timer.start(1000)
            self.crash_guard.start_hang_watchdog()

        QTimer.singleShot(80, self._phase2_warmup)

    def showEvent(self, event) -> None:  # noqa: N802
        super().showEvent(event)
        apply_window_theme(int(self.winId()), dark=(self.policy.config.theme_mode != "light"))

    def closeEvent(self, event) -> None:  # noqa: N802
        if not self._force_quit:
            event.ignore()
            self.hide()
            self.telemetry_timer.setInterval(10000)
            return
        self._shutdown_everything()
        event.accept()

    def _shutdown_everything(self, wait_s: float = SHUTDOWN_WAIT_S) -> dict[str, int]:
        """v0.5.9: cierre TOTAL. Antes se esperaban 3 s y la tarea seguia sin ventana (17/11: una
        Autolimpieza continuo 12 minutos tras "Salir"). Ahora: cancelar todas las tareas en un punto
        seguro (lo hecho queda registrado), esperar, y cerrar consolas y procesos hijos de la app."""
        if getattr(self, "_shutdown_done", False):
            return {"closed": 0, "failed": 0, "pending_tasks": 0}
        self._shutdown_done = True
        self._breadcrumb("Cierre total: cancelando tareas y procesos derivados")
        for t in (
            self.telemetry_timer,
            self.advisor_timer,
            self.update_check_timer,
            self.heartbeat_timer,
            self.task_eta_timer,
        ):
            t.stop()
        workers = list(self._active_workers)
        for w in workers:
            w.controller.cancel()
        for t in list(getattr(self.storage_view, "_quick_tasks", [])):
            t.controller.cancel()
        global_pool = QThreadPool.globalInstance()
        deadline = time.monotonic() + wait_s
        if global_pool.activeThreadCount() > 0:
            self._set_status("Cerrando de forma segura: guardando lo avanzado...")
            while global_pool.activeThreadCount() > 0 and time.monotonic() < deadline:
                QApplication.processEvents()
                global_pool.waitForDone(100)
        pending = global_pool.activeThreadCount()
        res = terminate_app_child_processes()
        res["pending_tasks"] = pending
        try:
            self.metrics_history.shutdown()
        except Exception:  # noqa: BLE001
            pass
        self.tray.hide()
        if self.crash_guard is not None:
            self.crash_guard.write_log_block(
                "CIERRE TOTAL",
                f"Tareas canceladas: {len(workers)} | procesos hijos cerrados: {res['closed']} "
                f"(no cerrados: {res['failed']}) | tareas aun activas tras {wait_s:.0f} s: {pending}",
            ) if (workers or res["closed"] or res["failed"] or pending) else None
        self._mark_clean_exit()
        return res

    def _mark_clean_exit(self) -> None:
        if self.crash_guard is not None:
            self.crash_guard.mark_clean_exit()

    def restore_from_tray(self) -> None:
        """v0.5.8: tambien la usa la segunda instancia (instancia unica) para traer la ventana."""
        self._restore_from_tray()

    def _restore_from_tray(self) -> None:
        self.telemetry_timer.setInterval(2000)
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _quit_app(self) -> None:
        # v0.5.9: confirmar si hay consolas de mantenimiento (DISM/SFC/CHKDSK) que se interrumpiran.
        consoles = running_tracked_children()
        servicing = [c for c in consoles if any(k in c.lower() for k in ("dism", "sfc", "chkdsk"))]
        if servicing:
            reply = QMessageBox.warning(
                self,
                "Cerrar WinOptiAI",
                "Al salir se cierran todas las tareas y consolas iniciadas desde la app.\n\n"
                "Hay una reparacion de Windows en curso:\n  - " + "\n  - ".join(servicing[:4]) + "\n\n"
                "Interrumpirla puede dejarla incompleta (podra repetirla despues). Desea cerrar todo?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return
        self._force_quit = True
        self._shutdown_everything()
        QApplication.quit()

    def _breadcrumb(self, message: str) -> None:
        if self.crash_guard is not None:
            self.crash_guard.breadcrumb(message)

    def _switch_tab(self, index: int) -> None:
        self._breadcrumb(f"Vista {index}")
        self.stack.setCurrentIndex(index)
        for i, btn in enumerate(self.nav_buttons):
            btn.setProperty("active", i == index)
            btn.style().unpolish(btn)
            btn.style().polish(btn)
        if index == 2:
            self.processes_view.refresh_all()

    def _set_status(self, message: str) -> None:
        self.status_lbl.setText(message)

    def _refresh_bell_badge(self) -> None:
        unread = self.notif_center.unread_count()
        self.bell_btn.setText(f" {unread}")

    def _notify_user(
        self,
        kind: str,
        title: str,
        detail: str,
        action_tab: int | None = None,
        tray_toast: bool = False,
    ) -> None:
        self.notif_center.add(kind, title, detail, action_tab=action_tab)
        self._refresh_bell_badge()
        if self._notif_dialog is not None and self._notif_dialog.isVisible():
            self._notif_dialog.refresh()
        if tray_toast and not self.isVisible():
            self.tray.showMessage(f"WinOptiAI - {title}", detail)

    def _open_notifications_drawer(self) -> None:
        if self._notif_dialog is None:
            self._notif_dialog = NotificationsTasksDialog(
                center=self.notif_center,
                active_tasks_fn=lambda: list(self._active_workers),
                on_jump_tab=self._switch_tab,
                theme_mode=self.policy.config.theme_mode,
                session_mgr=self.session_mgr,
                on_resume_session=self._resume_saved_session,
                on_sync_tasks=self._sync_active_task_indicators,
                parent=self,
                on_open_diagnostics=self._open_crash_diagnostics if self.crash_guard is not None else None,
            )
        self._notif_dialog.theme_mode = self.policy.config.theme_mode
        self._notif_dialog.refresh()
        self._notif_dialog.show()
        self._notif_dialog.raise_()
        self._notif_dialog.activateWindow()
        self.notif_center.mark_all_read()
        self._refresh_bell_badge()

    def _request_admin_relaunch(self) -> None:
        reply = QMessageBox.question(
            self,
            "Elevar a Modo Administrador (UAC)",
            "Desea relanzar WinOptiAI como Administrador para limpiar archivos residuales "
            "de Windows (Temp/Minidump/WER) y leer sensores ACPI/NVMe?\n\n"
            "Las listas blancas del sistema operativo siguen protegidas e intocables.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        if getattr(sys, "frozen", False):
            ok = run_elevated_command(sys.executable, ELEVATED_RELAUNCH_ARG)
        else:
            ok = run_elevated_command(sys.executable, f"-m winoptiai.app {ELEVATED_RELAUNCH_ARG}")
        if ok:
            self._quit_app()

    def _toggle_theme(self) -> None:
        new_mode = "light" if self.policy.config.theme_mode == "dark" else "dark"
        self.policy.config.theme_mode = new_mode
        self.policy.save_config()
        self._apply_ui_appearance()

    def _on_language_changed(self) -> None:
        lang = str(self.lang_combo.currentData() or "es")
        self.policy.config.language = lang
        self.policy.save_config()
        self._apply_ui_appearance()

    def _refresh_theme_button_icon(self, mode: str, color: str) -> None:
        if mode == "light":
            self.theme_btn.setIcon(load_svg_icon("moon", color=color, size=15))
            self.theme_btn.setToolTip("Cambiar a modo oscuro (cuaderno grafito)")
        else:
            self.theme_btn.setIcon(load_svg_icon("sun", color=color, size=15))
            self.theme_btn.setToolTip("Cambiar a modo claro (papel de libreta)")

    def _apply_ui_appearance(self) -> None:
        mode = self.policy.config.theme_mode
        lang = self.policy.config.language
        pal = get_palette(mode)

        self.root_canvas.set_theme_mode(mode)
        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(build_obsidian_qss(mode))
        apply_window_theme(int(self.winId()), dark=(mode != "light"))

        self.brand_icon.setPixmap(load_svg_pixmap("brand", color=pal["icon_color"], size=18))
        self.bell_btn.setIcon(load_svg_icon("bell", color=pal["icon_color"], size=15))
        self.tour_btn.setText(f" {tr('btn_tour', lang)}")
        self.tour_btn.setIcon(load_svg_icon("overview", color=pal["icon_color"], size=13))
        self._refresh_about_badge()
        self.about_btn.setIcon(load_svg_icon("shield", color=pal["icon_color"], size=13))
        self._refresh_theme_button_icon(mode, pal["icon_color"])

        for btn, (icon_name, tr_key) in zip(self.nav_buttons, self._nav_spec):
            btn.setText(f"  {tr(tr_key, lang)}")
            btn.setIcon(load_svg_icon(icon_name, color=pal["icon_color"], size=15))
            if tr_key in TOOLTIPS:
                btn.setToolTip(TOOLTIPS[tr_key])

        self.overview_view.apply_language_and_theme(lang, mode, pal["icon_inverted"])
        self.storage_view.apply_language_and_theme(lang, pal["icon_inverted"], mode)
        self.processes_view.apply_language_and_theme(lang, pal["icon_inverted"])
        self.thermal_view.apply_language_and_theme(lang, pal["icon_inverted"])
        self._sync_tray_state()

    def _open_about_dialog(self) -> None:
        rep = self.thermal_view.last_report
        if rep:
            hw_summary = (
                f"{rep.manufacturer} {rep.model} | {rep.cpu_name} | "
                f"{rep.gpu_name} | {rep.total_ram_gb:.1f} GB RAM"
            )
        else:
            ram_gb = psutil.virtual_memory().total / (1024**3)
            hw_summary = f"Windows x64 | {psutil.cpu_count(logical=True)} hilos | {ram_gb:.1f} GB RAM"
        dlg = AboutUpdaterDialog(
            lang=self.policy.config.language,
            theme_mode=self.policy.config.theme_mode,
            run_async=self._run_async,
            hardware_summary=hw_summary,
            active_tasks_fn=lambda: list(self._active_workers),
            parent=self,
            on_open_diagnostics=self._open_crash_diagnostics if self.crash_guard is not None else None,
            on_open_tour=self._open_tour_dialog,
            preloaded_release=self._available_update,
        )
        dlg.exec()

    def _open_about_from_tray(self) -> None:
        self._restore_from_tray()
        QTimer.singleShot(0, self._open_about_dialog)

    def _refresh_about_badge(self) -> None:
        lang = self.policy.config.language
        if self._available_update is not None and self._available_update.update_available:
            self.about_btn.setText(f" Nueva {self._available_update.tag}")
            self.about_btn.setToolTip(
                f"Nueva actualizacion disponible ({self._available_update.tag}). Clic para instalar."
            )
        else:
            self.about_btn.setText(f" {tr('btn_about', lang)}")
            self.about_btn.setToolTip(TOOLTIPS["btn_about"])

    def _open_tour_dialog(self) -> None:
        if self._tour_dialog is not None and self._tour_dialog.isVisible():
            self._tour_dialog.raise_()
            self._tour_dialog.activateWindow()
            return

        def _on_done(report: QuickCheckReport | None) -> None:
            if report is not None:
                self.policy.record_audit_event(
                    "usuario",
                    "Tour y Prueba Rapida",
                    f"Verificacion completada ({len(report.items)} chequeos) | Umbral SRE {report.recommended_threshold_gb:.1f} GB",
                )
                self.overview_view.set_audit_rows(self.policy.read_recent_audit())
                self._sample_telemetry()
                self._set_status("Tour y prueba rapida del sistema completados.")

        self._tour_dialog = QuickTourDialog(
            policy=self.policy,
            vault=self.vault,
            run_async=self._run_async,
            on_switch_tab=self._switch_tab,
            on_completed=_on_done,
            parent=self,
        )
        self._tour_dialog.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._tour_dialog.destroyed.connect(lambda _=None: setattr(self, "_tour_dialog", None))
        self._tour_dialog.show()
        self._tour_dialog.raise_()
        self._tour_dialog.activateWindow()

    def _open_crash_diagnostics(self) -> None:
        if self.crash_guard is None:
            return
        dlg = CrashReportDialog(self.crash_guard, parent=self)
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        dlg.show()
        dlg.raise_()
        dlg.activateWindow()

    def _report_previous_dirty_exit(self) -> None:
        """Notificar (campanita + audit.jsonl) si la sesion previa termino abruptamente."""
        guard = self.crash_guard
        if guard is None or guard.previous_session is None or not guard.previous_session.dirty:
            return
        prev = guard.previous_session
        detail = (
            f"{prev.summary()} Diagnostico guardado en {guard.crash_log_path}. "
            "Abra Notificaciones > Diagnostico o Acerca de > Diagnostico para verlo o copiarlo."
        )
        self.policy.record_audit_event("crash_guard", "Cierre inesperado detectado", prev.summary())
        self.overview_view.set_audit_rows(self.policy.read_recent_audit())
        self._notify_user("ERROR", "Cierre inesperado en la sesion anterior", detail, tray_toast=True)

        def _query_events() -> list[str]:
            return guard.query_recent_appcrash_events(max_events=3)

        def _on_events(entries: list[str]) -> None:
            prev.event_log_entries = list(entries)
            if entries:
                self.policy.record_audit_event(
                    "crash_guard", "Visor de eventos APPCRASH", " || ".join(entries)[:600]
                )
                self.overview_view.set_audit_rows(self.policy.read_recent_audit())
                guard.write_log_block("EVENTOS APPCRASH/HANG (Application, ID 1000/1002)", "\n".join(entries))
            self._prompt_crash_report(KIND_CRASH)

        # v0.5.3: el aviso de envio sale siempre tras un cierre inesperado, aunque falle la consulta.
        self._run_async(
            _query_events,
            _on_events,
            "Consulta Visor de eventos",
            notify_on_complete=False,
            on_error=lambda _e: self._prompt_crash_report(KIND_CRASH),
        )

    def _prompt_crash_report(self, kind: str, error_type: str = "", error_text: str = "") -> None:
        """Aviso tipo Windows: preguntar si enviar el informe anonimizado a GitHub."""
        guard = self.crash_guard
        if guard is None or self._crash_dialog is not None:
            return

        def _decided(sent: bool) -> None:
            what = "Cierre inesperado" if kind == KIND_CRASH else f"Error {error_type}"
            self.policy.record_audit_event(
                "crash_guard",
                "Informe de error",
                f"{what}: {'abierto en GitHub para enviar' if sent else 'el usuario decidio no enviarlo'}",
            )
            self.overview_view.set_audit_rows(self.policy.read_recent_audit())

        dlg = CrashSendDialog(
            guard,
            kind=kind,
            error_type=error_type,
            error_text=error_text,
            auto_restarted=self.auto_restarted,
            on_decision=_decided,
            parent=self,
        )
        dlg.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self._crash_dialog = dlg
        dlg.finished.connect(lambda _r: setattr(self, "_crash_dialog", None))
        if self.isHidden():
            self.showNormal()
        dlg.open()
        dlg.raise_()
        dlg.activateWindow()

    def _on_unhandled_error(self, origin: str, error_type: str, text: str) -> None:
        # Una sola vez por error distinto y como maximo 3 avisos por sesion (sin cascadas).
        last_frame = next((ln.strip() for ln in reversed(text.splitlines()) if ln.strip().startswith("File ")), "")
        key = f"{error_type}|{last_frame}"
        if key in self._reported_error_keys or len(self._reported_error_keys) >= MAX_ERROR_PROMPTS_PER_SESSION:
            return
        self._reported_error_keys.add(key)
        self._prompt_crash_report(KIND_ERROR, error_type=error_type, error_text=f"[{origin}]\n{text}")

    def _on_elevated_temps(self, cpu_c: float | None, nvme_c: float | None) -> None:
        self.telemetry_reader.set_elevated_temps(cpu_c, nvme_c)
        self._sample_telemetry()

    def _toggle_lead_pause(self) -> None:
        if not self._active_workers:
            return
        lead = self._active_workers[0]
        if lead.controller.is_paused:
            lead.controller.resume()
        else:
            lead.controller.pause()
        self._sync_active_task_indicators()

    def _save_and_pause_lead(self) -> None:
        if not self._active_workers:
            return
        self._active_workers[0].controller.pause_and_save()
        self._set_status("Guardando sesion en punto seguro...")

    def _cancel_lead_task(self) -> None:
        if not self._active_workers:
            return
        self._active_workers[0].controller.cancel()
        self._set_status("Cancelando proceso de forma segura...")

    def _resume_saved_session(self, session: TaskSessionRecord) -> None:
        if session.kind == "rescan":  # v0.5.9: analisis guardado (Duplicados / Arbol)
            self.session_mgr.remove_session(session.session_id)
            self._switch_tab(1)
            if not self.storage_view.resume_scan(session.meta):
                self._set_status("No se pudo retomar: la carpeta ya no existe.")
            self._sync_active_task_indicators()
            return
        if session.kind != "junk_clean":
            self.session_mgr.remove_session(session.session_id)
            self._sync_active_task_indicators()
            return

        def _work(progress_cb=None, controller=None) -> dict[str, int]:
            return resume_junk_session(
                session,
                self.vault,
                session_mgr=self.session_mgr,
                progress_cb=progress_cb,
                controller=controller,
            )

        def _done(res: dict[str, int]) -> None:
            from .theme import format_bytes

            msg = (
                f"Sesion retomada completada: {res['removed']} archivos asegurados, "
                f"{format_bytes(res['freed'])} recuperados."
            )
            self.policy.record_audit_event("usuario", "Reanudacion sesion", msg, res["freed"] / (1024 * 1024))
            self.overview_view.set_audit_rows(self.policy.read_recent_audit())
            self._set_status(msg)
            self._notify_user("COMPLETADO", session.title, msg, action_tab=1, tray_toast=True)
            self._sync_active_task_indicators()

        self._run_async(
            _work,
            _done,
            f"Retomando: {session.title}",
            notify_on_complete=False,
            progress_ui_cb=lambda p, s: self.storage_view._progress_summary(p, s),
            supports_save=True,
        )

    def _sync_active_task_indicators(self) -> None:
        summaries: list[str] = []
        for w in self._active_workers:
            eta = w.eta_label()
            summaries.append(f"{w.title} ({w.percent}%{' · ' + eta if eta else ''})")
        self.overview_view.set_active_tasks(summaries)
        self.processes_view.set_active_tasks(summaries)

        has_active = bool(self._active_workers)
        self.pause_top_btn.setVisible(has_active)
        lead_can_save = has_active and bool(getattr(self._active_workers[0], "supports_save", False))
        self.save_pause_top_btn.setVisible(lead_can_save)
        self.cancel_top_btn.setVisible(has_active)

        saved_sessions = self.session_mgr.list_sessions()
        self.resume_session_btn.setVisible(bool(saved_sessions))
        if saved_sessions:
            self.resume_session_btn.set_variants([f"Retomar Sesion ({len(saved_sessions)})", f"Retomar ({len(saved_sessions)})", "Retomar"])

        if has_active:
            if not self.task_eta_timer.isActive():
                self.task_eta_timer.start()
            lead = self._active_workers[0]
            self.pause_top_btn.setText("Reanudar" if lead.controller.is_paused else "Pausar")
            eta = lead.eta_label()
            eta_part = f" · {eta}" if eta else ""
            extra = f" (+{len(self._active_workers) - 1})" if len(self._active_workers) > 1 else ""
            self.task_pill_btn.set_variants(_task_pill_variants(lead.title, lead.percent, eta_part, extra))
        else:
            if self.task_eta_timer.isActive():
                self.task_eta_timer.stop()
            self.task_pill_btn.set_variants(["Sin procesos en segundo plano", "Sin tareas"])
        if self._notif_dialog is not None and self._notif_dialog.isVisible():
            self._notif_dialog._render_tasks()
            self._notif_dialog._render_sessions()
        self._sync_tray_state()

    def _run_async(
        self,
        fn,
        callback,
        task_label: str = "Tarea en segundo plano",
        notify_on_complete: bool = True,
        progress_ui_cb=None,
        on_error=None,
        supports_save: bool = False,
        resume_meta: dict | None = None,
    ) -> None:
        # RAM-aware concurrency guardrail
        free_gb = get_memory_snapshot()["free_gb"]
        if len(self._active_workers) >= MAX_CONCURRENT_TASKS:
            msg = f"Cola llena ({MAX_CONCURRENT_TASKS} procesos en curso). Espere un momento."
            self._set_status(msg)
            self._notify_user("AVISO", "Limite de concurrencia", msg)
            if on_error is not None:
                on_error(msg)
            return
        if len(self._active_workers) >= 1 and free_gb < MIN_RAM_FOR_NEW_TASK_GB:
            msg = (
                f"RAM libre muy baja ({free_gb:.2f} GB < {MIN_RAM_FOR_NEW_TASK_GB:.1f} GB) "
                "para lanzar otro proceso paralelo. Ejecuta AI Boost primero."
            )
            self._set_status(msg)
            self._notify_user("AVISO", "Proteccion de RAM activa", msg, action_tab=0)
            if on_error is not None:
                on_error(msg)
            return

        worker = AsyncTask(task_label, fn)
        # v0.5.7: solo las tareas que guardan su punto exacto (limpieza de temporales) ofrecen
        # "Guardar Pausa"; en las demas el boton no hacia nada y la tarea seguia corriendo.
        worker.supports_save = supports_save or resume_meta is not None
        if resume_meta is not None:
            # v0.5.9: "Guardar Pausa" en analisis -> sesion "rescan" que Retomar Sesion relanza
            # (Duplicados reutiliza las huellas ya calculadas en hash_cache.sqlite).
            def _save(percent: int, meta=dict(resume_meta), title=task_label) -> str:
                sid = new_session_id()
                self.session_mgr.save_session(
                    TaskSessionRecord(
                        session_id=sid,
                        kind="rescan",
                        title=title,
                        created_at=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
                        percent=int(percent),
                        total_items=0,
                        processed_items=0,
                        meta=meta,
                    )
                )
                return sid

            worker.save_handler = _save
        self._active_workers.append(worker)
        self._breadcrumb(f"Tarea iniciada: {task_label}")
        self._sync_active_task_indicators()

        def _on_progress(_tid: str, pct: int, stage: str) -> None:
            self._sync_active_task_indicators()
            if progress_ui_cb is not None:
                try:
                    progress_ui_cb(pct, stage)
                except RuntimeError:
                    pass

        def _cleanup_common(tid: str) -> None:
            finished = [w for w in self._active_workers if w.task_id == tid]
            self._active_workers[:] = [w for w in self._active_workers if w.task_id != tid]
            if finished:
                self._retired_workers.extend(finished)
                QTimer.singleShot(0, self._release_retired_workers)
            self._sync_active_task_indicators()

        def _cleanup_and_emit(tid: str, result) -> None:
            _cleanup_common(tid)
            callback(result)
            if notify_on_complete:
                self._notify_user(
                    "COMPLETADO",
                    task_label,
                    "Proceso finalizado correctamente en segundo plano.",
                    tray_toast=True,
                )

        def _cleanup_on_paused_saved(tid: str, _sid: str, pct: int, detail: str) -> None:
            _cleanup_common(tid)
            self._set_status(detail)
            self._notify_user("AVISO", f"{task_label} (Pausado {pct}%)", detail, action_tab=1, tray_toast=True)
            if on_error is not None:
                on_error(detail)

        def _cleanup_on_canceled(tid: str, detail: str) -> None:
            _cleanup_common(tid)
            self._set_status(detail)
            self._notify_user("AVISO", f"{task_label} (Cancelado)", detail, tray_toast=False)
            if on_error is not None:
                on_error(detail)

        def _cleanup_on_err(tid: str, err: str) -> None:
            _cleanup_common(tid)
            self._breadcrumb(f"Tarea con error: {task_label}: {err[:160]}")
            self._set_status(f"Aviso: {err}")
            self._notify_user("ERROR", task_label, err, tray_toast=True)
            if on_error is not None:
                on_error(err)

        # Conexion en cola explicita: los callbacks tocan widgets y deben ejecutarse siempre
        # en el hilo GUI, nunca en el hilo del QThreadPool que emite la senal.
        queued = Qt.ConnectionType.QueuedConnection
        worker.signals.progress.connect(_on_progress, queued)
        worker.signals.finished.connect(_cleanup_and_emit, queued)
        worker.signals.paused_saved.connect(_cleanup_on_paused_saved, queued)
        worker.signals.canceled.connect(_cleanup_on_canceled, queued)
        worker.signals.error.connect(_cleanup_on_err, queued)
        self.pool.start(worker)

    def _release_retired_workers(self) -> None:
        self._retired_workers.clear()

    def _phase2_warmup(self) -> None:
        self._report_previous_dirty_exit()
        self._refresh_disk_stats()
        self._sample_telemetry()
        self._sync_active_task_indicators()
        self.overview_view.set_audit_rows(self.policy.read_recent_audit())
        self.thermal_view.refresh_audit()

        def _retain_quarantine() -> dict[str, int]:
            return self.vault.purge_expired_items(max_age_days=30, only_junk_categories=True)

        def _on_retained(res: dict[str, int]) -> None:
            if res.get("purged", 0) > 0:
                self.policy.record_audit_event(
                    "sre_auto",
                    "Auto-expiracion Cuarentena (30d)",
                    f"Purgados {res['purged']} lotes temporales expirados",
                    res.get("freed_bytes", 0) / (1024 * 1024),
                )
                self.overview_view.set_audit_rows(self.policy.read_recent_audit())

        self._run_async(_retain_quarantine, _on_retained, "Retencion Cuarentena 30d", notify_on_complete=False)
        self._sync_tray_state()
        if (
            not self.policy.config.onboarding_completed
            and self.isVisible()
            and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
            and not self.auto_restarted
        ):
            QTimer.singleShot(450, self._open_tour_dialog)
        if (
            self.policy.config.auto_check_updates
            and os.environ.get("QT_QPA_PLATFORM") != "offscreen"
        ):
            QTimer.singleShot(5000, self._check_updates_background)

    def _refresh_disk_stats(self) -> None:
        try:
            usage = psutil.disk_usage("C:\\")
            self._disk_free_gb = round(usage.free / (1024**3), 2)
            self._disk_total_gb = round(usage.total / (1024**3), 2)
        except OSError:
            pass

    def _sample_telemetry(self) -> None:
        ram = get_memory_snapshot()
        live = self.telemetry_reader.sample()
        if self._disk_total_gb == 0.0:
            self._refresh_disk_stats()

        prof = THERMAL_PROFILES.get(self.policy.config.active_thermal_profile)
        thermal_label = prof.title if prof else "Equilibrado"

        self.overview_view.update_telemetry(
            ram=ram,
            live=live,
            disk_free_gb=self._disk_free_gb,
            disk_total_gb=self._disk_total_gb,
            sre_active=self.policy.config.auto_ram_relief_enabled,
            threshold_gb=self.policy.config.ram_threshold_gb,
            thermal_label=thermal_label,
        )
        self.thermal_view.update_live_telemetry(live)

        # v0.5.8: un punto por minuto (promedio de las lecturas de 2 s) escrito fuera del hilo GUI.
        minute = self._minute_agg.add(ram["free_gb"], ram["total_gb"], live.cpu_utility_pct, live.cpu_temp_c)
        if minute is not None:
            self.metrics_history.record_async(minute)
            # La hebra de metricas es FIFO: la recarga se ejecuta despues de la escritura.
            if self.isVisible():
                self.overview_view.schedule_history_refresh(200)

        if self.policy.evaluate_ram_pressure(ram["free_gb"]):
            self._execute_ai_boost("sre_auto")

    def _run_periodic_advisor(self) -> None:
        """Quietly evaluate storage/zombie/RAM deltas every 15 minutes."""
        def _probe() -> list[dict]:
            ram = get_memory_snapshot()
            targets = scan_junk_targets()
            junk_gb = sum(t.reclaimable_bytes for t in targets) / (1024**3)
            zombies = detect_orphan_ai_workers()
            z_mb = sum(z.ram_mb for z in zombies)
            return self.advisor.evaluate(
                free_ram_gb=ram["free_gb"],
                ram_threshold_gb=self.policy.config.ram_threshold_gb,
                temp_junk_gb=junk_gb,
                zombie_count=len(zombies),
                zombie_ram_mb=z_mb,
            )

        def _done(suggestions: list[dict]) -> None:
            for sug in suggestions:
                self._notify_user(
                    "SUGERENCIA",
                    sug["title"],
                    sug["detail"],
                    action_tab=sug.get("action_tab"),
                    tray_toast=True,
                )

        self._run_async(_probe, _done, "Asesor periodico SRE", notify_on_complete=False)

    def _execute_ai_boost(self, actor: str) -> None:
        self.overview_view.boost_btn.setEnabled(False)
        self.processes_view.boost_btn.setEnabled(False)
        self._set_status("Optimizando Working Set y EcoQoS...")

        def _work(progress_cb=None) -> dict[str, float | int]:
            snap = get_memory_snapshot()
            self.backup_mgr.create_operation_snapshot("ai_boost", [snap])
            return run_ai_boost(
                trim_heavy_apps=True,
                apply_ecoqos=self.policy.config.auto_ecoqos_background_browsers,
                progress_cb=progress_cb,
            )

        def _re_enable(_err: str = "") -> None:
            self.overview_view.boost_btn.setEnabled(True)
            self.processes_view.boost_btn.setEnabled(True)

        def _done(res: dict[str, float | int]) -> None:
            _re_enable()
            msg = (
                f"RAM libre: {res['free_before_gb']:.2f} -> {res['free_after_gb']:.2f} GB "
                f"(+{res['freed_mb']:.0f} MB, {res['trimmed_processes']} procesos compactados, "
                f"{res['ecoqos_applied']} en EcoQoS)"
            )
            self.policy.record_audit_event(actor, "AI Boost", msg, float(res["freed_mb"]))
            self.overview_view.set_audit_rows(self.policy.read_recent_audit())
            self._set_status(msg)
            self._sample_telemetry()
            self._notify_user("COMPLETADO", "AI Boost", msg, action_tab=0, tray_toast=(actor == "sre_auto"))

        self._run_async(_work, _done, "AI Boost (RAM + EcoQoS)", notify_on_complete=False, on_error=_re_enable)

    def _on_thermal_audit_updated(self) -> None:
        self.overview_view.set_audit_rows(self.policy.read_recent_audit())
        self._sync_tray_state()

    def _sync_tray_state(self) -> None:
        if not hasattr(self, "tray"):
            return
        task_txt = ""
        if self._active_workers:
            lead = self._active_workers[0]
            task_txt = f"{lead.title} ({lead.percent}%)"
        upd_tag = (
            self._available_update.tag
            if self._available_update is not None and self._available_update.update_available
            else ""
        )
        self.tray.sync_state(
            thermal_key=self.policy.config.active_thermal_profile,
            sre_enabled=self.policy.config.auto_ram_relief_enabled,
            theme_mode=self.policy.config.theme_mode,
            task_summary=task_txt,
            available_update=upd_tag,
        )

    def _check_updates_background(self) -> None:
        """Silently query GitHub Releases once at startup and every 12h; notify once per new version."""
        if (
            not self.policy.config.auto_check_updates
            or self._checking_updates
            or getattr(self, "_shutdown_done", False)
        ):
            return
        self._checking_updates = True

        def _probe() -> tuple[bool, ReleaseInfo | None, str]:
            return check_for_updates(__version__, timeout=6)

        def _done(res: tuple[bool, ReleaseInfo | None, str]) -> None:
            self._checking_updates = False
            ok, info, _msg = res
            self._handle_update_check_result(ok, info)

        def _err(_msg: str) -> None:
            self._checking_updates = False

        self._run_async(
            _probe,
            _done,
            "Verificar actualizaciones",
            notify_on_complete=False,
            on_error=_err,
        )

    def _handle_update_check_result(self, ok: bool, info: ReleaseInfo | None) -> bool:
        """Update badges, tray menu, and trigger once-per-version notification when newer release exists."""
        if getattr(self, "_shutdown_done", False):
            return False
        self.policy.config.last_update_check_ts = time.time()
        if not ok or info is None or not info.update_available:
            self.policy.save_config()
            return False

        self._available_update = info
        self._refresh_about_badge()
        self._sync_tray_state()

        if self.policy.config.last_notified_version == info.version:
            self.policy.save_config()
            return False

        self.policy.config.last_notified_version = info.version
        self.policy.save_config()
        title = f"Nueva version WinOptiAI {info.tag}"
        detail = (
            "Hay una actualizacion disponible en GitHub Releases. "
            f"Haz clic en 'Nueva {info.tag}' o en el menu de la bandeja para instalarla."
        )
        self.policy.record_audit_event("updater", "Actualizacion disponible", f"Release {info.tag} detectado")
        self.overview_view.set_audit_rows(self.policy.read_recent_audit())
        self._set_status(f"Actualizacion disponible: {info.tag}")
        self._notify_user("SUGERENCIA", title, detail, action_tab=None, tray_toast=True)
        if self.isVisible() and os.environ.get("QT_QPA_PLATFORM") != "offscreen":
            self.tray.showMessage(f"WinOptiAI - {title}", detail)
        return True

    def _tray_toggle_sre(self, enabled: bool) -> None:
        self.policy.config.auto_ram_relief_enabled = bool(enabled)
        self.policy.save_config()
        state_lbl = "activado" if enabled else "pausado"
        self.policy.record_audit_event("tray", "Guardia SRE", f"Guardia SRE automatico {state_lbl}")
        self.overview_view.set_audit_rows(self.policy.read_recent_audit())
        self._sample_telemetry()
        self._sync_tray_state()
        self._set_status(f"Guardia SRE automatico {state_lbl}.")

    def _tray_thermal(self, key: str) -> None:
        self.backup_mgr.backup_power_scheme(f"tray_{key}")
        ok, msg = apply_thermal_profile(key)
        if ok:
            self.policy.config.active_thermal_profile = key
            self.policy.save_config()
            self.thermal_view._highlight_profile_button(key)
            self.policy.record_audit_event("tray", "Perfil termico", msg)
            self.overview_view.set_audit_rows(self.policy.read_recent_audit())
            self._sync_tray_state()
        self._set_status(msg)
        self._notify_user("COMPLETADO", "Perfil termico", msg, action_tab=3, tray_toast=True)
