"""Main Obsidian/Alabaster Acrylic window with Top Utility Bar, Bell Drawer, and Concurrent Hub."""

from __future__ import annotations

import sys

import psutil
from PySide6.QtCore import Qt, QThreadPool, QTimer
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
from ..core.i18n import tr
from ..core.notifications import NotificationCenter, PeriodicAdvisor
from ..core.safety_guard import PreOpBackupManager, QuarantineVault
from ..core.sre_policy import SREPolicyEngine
from ..core.telemetry import PdhTelemetryReader
from ..core.win32_bridge import apply_window_theme, is_user_admin, run_elevated_command
from ..storage.junk_scanner import scan_junk_targets
from ..thermal_bios.thermal_controller import THERMAL_PROFILES, apply_thermal_profile
from .dialogs.about_updater_dialog import AboutUpdaterDialog
from .dialogs.notifications_drawer import NotificationsTasksDialog
from .svg_icons import load_svg_icon, load_svg_pixmap
from .system_tray import WinOptiTray
from .theme import build_obsidian_qss, get_palette
from .views.overview_view import OverviewView
from .views.processes_view import ProcessesView
from .views.storage_view import StorageView
from .views.thermal_bios_view import ThermalBiosView
from .widgets import NotebookCanvas, StatusTag
from .workers import AsyncTask


MAX_CONCURRENT_TASKS = 4
MIN_RAM_FOR_NEW_TASK_GB = 1.0


class MainWindow(QMainWindow):
    """Primary desktop shell with RAM-aware concurrent jobs, Bell drawer, and periodic advisor."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"WinOptiAI {__version__}")
        self.resize(1200, 760)
        self.setMinimumSize(980, 650)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(max(4, self.pool.maxThreadCount()))
        self._active_workers: list[AsyncTask] = []
        self._notif_dialog: NotificationsTasksDialog | None = None

        self.vault = QuarantineVault()
        self.backup_mgr = PreOpBackupManager()
        self.policy = SREPolicyEngine()
        self.notif_center = NotificationCenter()
        self.advisor = PeriodicAdvisor(cooldown_seconds=7200)
        self.telemetry_reader = PdhTelemetryReader()
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
        sidebar.setFixedWidth(232)
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
        ctl_row.addWidget(self.lang_combo, stretch=1)
        f_layout.addLayout(ctl_row)

        self.about_btn = QPushButton(f" {tr('btn_about', lang)}")
        self.about_btn.setObjectName("GhostAction")
        self.about_btn.setIcon(load_svg_icon("shield", color=pal["icon_color"], size=13))
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

        self.task_pill_btn = QPushButton("Sin procesos en segundo plano")
        self.task_pill_btn.setObjectName("GhostAction")
        self.task_pill_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.task_pill_btn.clicked.connect(self._open_notifications_drawer)
        tb_layout.addWidget(self.task_pill_btn)
        tb_layout.addStretch()

        is_admin = is_user_admin()
        self.admin_tag = StatusTag("ADMIN UAC" if is_admin else "MODO ESTANDAR", "ok" if is_admin else "neutral")
        tb_layout.addWidget(self.admin_tag)

        if not is_admin:
            self.uac_btn = QPushButton("Elevar Admin (UAC)")
            self.uac_btn.setObjectName("GhostAction")
            self.uac_btn.setToolTip(
                "Relanzar como Administrador para limpiar residuos de Windows (Temp/WER/Minidump) sin tocar archivos del SO"
            )
            self.uac_btn.setCursor(Qt.CursorShape.PointingHandCursor)
            self.uac_btn.clicked.connect(self._request_admin_relaunch)
            tb_layout.addWidget(self.uac_btn)

        self.bell_btn = QPushButton(" 0")
        self.bell_btn.setObjectName("BellBtn")
        self.bell_btn.setIcon(load_svg_icon("bell", color=pal["icon_color"], size=15))
        self.bell_btn.setToolTip("Abrir centro de notificaciones y progreso de tareas")
        self.bell_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.bell_btn.clicked.connect(self._open_notifications_drawer)
        tb_layout.addWidget(self.bell_btn)
        rc_layout.addWidget(top_bar)

        # Stacked Views
        self.stack = QStackedWidget()
        self.overview_view = OverviewView(lang=lang)
        self.overview_view.trigger_ai_boost.connect(lambda: self._execute_ai_boost("usuario"))
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
        self.thermal_view.audit_log_updated.connect(
            lambda: self.overview_view.set_audit_rows(self.policy.read_recent_audit())
        )

        self.stack.addWidget(self.overview_view)
        self.stack.addWidget(self.storage_view)
        self.stack.addWidget(self.processes_view)
        self.stack.addWidget(self.thermal_view)
        rc_layout.addWidget(self.stack, stretch=1)
        main_layout.addWidget(right_col, stretch=1)

        # Apply active palette icons across all views immediately on first frame
        self._apply_ui_appearance()

        # System Tray
        self.tray = WinOptiTray(
            self,
            on_show=self._restore_from_tray,
            on_boost=lambda: self._execute_ai_boost("usuario"),
            on_thermal=self._tray_thermal,
            on_quit=self._quit_app,
        )
        self.tray.show()

        self._switch_tab(0)
        self._refresh_bell_badge()

        # Live telemetry timer
        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.timeout.connect(self._sample_telemetry)
        self.telemetry_timer.start(2000)

        # Low-noise periodic optimization advisor (every 15 minutes)
        self.advisor_timer = QTimer(self)
        self.advisor_timer.timeout.connect(self._run_periodic_advisor)
        self.advisor_timer.start(900_000)

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
        self.telemetry_timer.stop()
        self.advisor_timer.stop()
        self.tray.hide()
        self.pool.waitForDone(3000)
        event.accept()

    def _restore_from_tray(self) -> None:
        self.telemetry_timer.setInterval(2000)
        self.showNormal()
        self.activateWindow()
        self.raise_()

    def _quit_app(self) -> None:
        self._force_quit = True
        QApplication.quit()

    def _switch_tab(self, index: int) -> None:
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
                parent=self,
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
            ok = run_elevated_command(sys.executable, "")
        else:
            ok = run_elevated_command(sys.executable, "-m winoptiai.app")
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
        self.about_btn.setText(f" {tr('btn_about', lang)}")
        self.about_btn.setIcon(load_svg_icon("shield", color=pal["icon_color"], size=13))
        self._refresh_theme_button_icon(mode, pal["icon_color"])

        for btn, (icon_name, tr_key) in zip(self.nav_buttons, self._nav_spec):
            btn.setText(f"  {tr(tr_key, lang)}")
            btn.setIcon(load_svg_icon(icon_name, color=pal["icon_color"], size=15))

        self.overview_view.apply_language_and_theme(lang, mode, pal["icon_inverted"])
        self.storage_view.apply_language_and_theme(lang, pal["icon_inverted"], mode)
        self.processes_view.apply_language_and_theme(lang, pal["icon_inverted"])
        self.thermal_view.apply_language_and_theme(lang, pal["icon_inverted"])

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
        )
        dlg.exec()

    def _on_elevated_temps(self, cpu_c: float | None, nvme_c: float | None) -> None:
        self.telemetry_reader.set_elevated_temps(cpu_c, nvme_c)
        self._sample_telemetry()

    def _sync_active_task_indicators(self) -> None:
        summaries = [f"{w.title} ({w.percent}%)" for w in self._active_workers]
        self.overview_view.set_active_tasks(summaries)
        self.processes_view.set_active_tasks(summaries)
        if self._active_workers:
            lead = self._active_workers[0]
            extra = f" (+{len(self._active_workers) - 1})" if len(self._active_workers) > 1 else ""
            self.task_pill_btn.setText(f"{lead.title}: {lead.percent}%{extra}")
        else:
            self.task_pill_btn.setText("Sin procesos en segundo plano")
        if self._notif_dialog is not None and self._notif_dialog.isVisible():
            self._notif_dialog._render_tasks()

    def _run_async(
        self,
        fn,
        callback,
        task_label: str = "Tarea en segundo plano",
        notify_on_complete: bool = True,
        progress_ui_cb=None,
    ) -> None:
        # RAM-aware concurrency guardrail
        free_gb = get_memory_snapshot()["free_gb"]
        if len(self._active_workers) >= MAX_CONCURRENT_TASKS:
            msg = f"Cola llena ({MAX_CONCURRENT_TASKS} procesos en curso). Espere un momento."
            self._set_status(msg)
            self._notify_user("AVISO", "Limite de concurrencia", msg)
            return
        if len(self._active_workers) >= 1 and free_gb < MIN_RAM_FOR_NEW_TASK_GB:
            msg = (
                f"RAM libre muy baja ({free_gb:.2f} GB < {MIN_RAM_FOR_NEW_TASK_GB:.1f} GB) "
                "para lanzar otro proceso paralelo. Ejecuta AI Boost primero."
            )
            self._set_status(msg)
            self._notify_user("AVISO", "Proteccion de RAM activa", msg, action_tab=0)
            return

        worker = AsyncTask(task_label, fn)
        self._active_workers.append(worker)
        self._sync_active_task_indicators()

        def _on_progress(_tid: str, pct: int, stage: str) -> None:
            self._sync_active_task_indicators()
            if progress_ui_cb is not None:
                try:
                    progress_ui_cb(pct, stage)
                except RuntimeError:
                    pass

        def _cleanup_common(tid: str) -> None:
            self._active_workers[:] = [w for w in self._active_workers if w.task_id != tid]
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

        def _cleanup_on_err(tid: str, err: str) -> None:
            _cleanup_common(tid)
            self._set_status(f"Aviso: {err}")
            self._notify_user("ERROR", task_label, err, tray_toast=True)

        worker.signals.progress.connect(_on_progress)
        worker.signals.finished.connect(_cleanup_and_emit)
        worker.signals.error.connect(_cleanup_on_err)
        self.pool.start(worker)

    def _phase2_warmup(self) -> None:
        self._refresh_disk_stats()
        self._sample_telemetry()
        self.overview_view.set_audit_rows(self.policy.read_recent_audit())
        self.thermal_view.refresh_audit()

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
        self._set_status("Optimizando Working Set y EcoQoS...")

        def _work(progress_cb=None) -> dict[str, float | int]:
            snap = get_memory_snapshot()
            self.backup_mgr.create_operation_snapshot("ai_boost", [snap])
            return run_ai_boost(
                trim_heavy_apps=True,
                apply_ecoqos=self.policy.config.auto_ecoqos_background_browsers,
                progress_cb=progress_cb,
            )

        def _done(res: dict[str, float | int]) -> None:
            self.overview_view.boost_btn.setEnabled(True)
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

        self._run_async(_work, _done, "AI Boost (RAM + EcoQoS)", notify_on_complete=False)

    def _tray_thermal(self, key: str) -> None:
        self.backup_mgr.backup_power_scheme(f"tray_{key}")
        ok, msg = apply_thermal_profile(key)
        if ok:
            self.policy.config.active_thermal_profile = key
            self.policy.save_config()
            self.thermal_view._highlight_profile_button(key)
            self.policy.record_audit_event("tray", "Perfil termico", msg)
            self.overview_view.set_audit_rows(self.policy.read_recent_audit())
        self._set_status(msg)
        self._notify_user("COMPLETADO", "Perfil termico", msg, action_tab=3, tray_toast=True)
