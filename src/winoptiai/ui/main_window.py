"""Main Obsidian/Alabaster Acrylic window with fluid two-phase startup, theme/lang toggle, and About."""

from __future__ import annotations

import psutil
from PySide6.QtCore import Qt, QThreadPool, QTimer
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QStackedWidget,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..ai_optimizer.process_manager import get_memory_snapshot, run_ai_boost
from ..core.i18n import tr
from ..core.safety_guard import QuarantineVault
from ..core.sre_policy import SREPolicyEngine
from ..core.telemetry import PdhTelemetryReader
from ..core.win32_bridge import apply_window_theme
from ..thermal_bios.thermal_controller import THERMAL_PROFILES, apply_thermal_profile
from .dialogs.about_updater_dialog import AboutUpdaterDialog
from .svg_icons import load_svg_icon, load_svg_pixmap
from .system_tray import WinOptiTray
from .theme import build_obsidian_qss, get_palette
from .views.overview_view import OverviewView
from .views.processes_view import ProcessesView
from .views.storage_view import StorageView
from .views.thermal_bios_view import ThermalBiosView
from .widgets import StatusTag
from .workers import AsyncTask


class MainWindow(QMainWindow):
    """Primary desktop shell engineered for instant first paint, live telemetry, and clean UX."""

    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(f"WinOptiAI {__version__}")
        self.resize(1180, 740)
        self.setMinimumSize(980, 640)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground, True)

        self.pool = QThreadPool.globalInstance()
        self._active_workers: list[AsyncTask] = []
        self._active_task_names: list[str] = []
        self.vault = QuarantineVault()
        self.policy = SREPolicyEngine()
        self.telemetry_reader = PdhTelemetryReader()
        self._disk_free_gb = 0.0
        self._disk_total_gb = 0.0
        self._force_quit = False

        lang = self.policy.config.language
        theme_mode = self.policy.config.theme_mode
        pal = get_palette(theme_mode)

        root_canvas = QWidget()
        root_canvas.setObjectName("RootCanvas")
        self.setCentralWidget(root_canvas)

        main_layout = QHBoxLayout(root_canvas)
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

        # Quiet footer: Theme toggle, Language selector, About & Updates, Active status
        footer = QWidget()
        f_layout = QVBoxLayout(footer)
        f_layout.setContentsMargins(14, 10, 14, 14)
        f_layout.setSpacing(8)

        ctl_row = QHBoxLayout()
        ctl_row.setSpacing(6)
        self.theme_btn = QPushButton(
            tr("btn_theme_light" if theme_mode == "light" else "btn_theme_dark", lang)
        )
        self.theme_btn.setObjectName("GhostAction")
        self.theme_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.theme_btn.clicked.connect(self._toggle_theme)
        ctl_row.addWidget(self.theme_btn, stretch=1)

        self.lang_combo = QComboBox()
        self.lang_combo.addItem("ES", "es")
        self.lang_combo.addItem("EN", "en")
        self.lang_combo.addItem("PT", "pt")
        idx_lang = self.lang_combo.findData(lang)
        if idx_lang >= 0:
            self.lang_combo.setCurrentIndex(idx_lang)
        self.lang_combo.currentIndexChanged.connect(self._on_language_changed)
        ctl_row.addWidget(self.lang_combo)
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

        # Stacked Views
        self.stack = QStackedWidget()
        self.overview_view = OverviewView(lang=lang)
        self.overview_view.trigger_ai_boost.connect(lambda: self._execute_ai_boost("usuario"))
        self.storage_view = StorageView(
            self.vault, self.policy, self._run_async, self._set_status, lang=lang
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
            self._run_async,
            self._set_status,
            self._on_elevated_temps,
            lang=lang,
        )

        self.stack.addWidget(self.overview_view)
        self.stack.addWidget(self.storage_view)
        self.stack.addWidget(self.processes_view)
        self.stack.addWidget(self.thermal_view)
        main_layout.addWidget(self.stack, stretch=1)

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

        # Live telemetry timer
        self.telemetry_timer = QTimer(self)
        self.telemetry_timer.timeout.connect(self._sample_telemetry)
        self.telemetry_timer.start(2000)

        # Phase 2 warmup after first paint
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

    def _apply_ui_appearance(self) -> None:
        mode = self.policy.config.theme_mode
        lang = self.policy.config.language
        pal = get_palette(mode)

        app = QApplication.instance()
        if isinstance(app, QApplication):
            app.setStyleSheet(build_obsidian_qss(mode))
        apply_window_theme(int(self.winId()), dark=(mode != "light"))

        self.brand_icon.setPixmap(load_svg_pixmap("brand", color=pal["icon_color"], size=18))
        self.about_btn.setText(f" {tr('btn_about', lang)}")
        self.about_btn.setIcon(load_svg_icon("shield", color=pal["icon_color"], size=13))
        self.theme_btn.setText(tr("btn_theme_light" if mode == "light" else "btn_theme_dark", lang))

        for btn, (icon_name, tr_key) in zip(self.nav_buttons, self._nav_spec):
            btn.setText(f"  {tr(tr_key, lang)}")
            btn.setIcon(load_svg_icon(icon_name, color=pal["icon_color"], size=15))

        self.overview_view.apply_language_and_theme(lang, mode, pal["icon_inverted"])
        self.storage_view.apply_language_and_theme(lang, pal["icon_inverted"])
        self.processes_view.apply_language_and_theme(lang, pal["icon_inverted"])
        self.thermal_view.apply_language_and_theme(lang, pal["icon_inverted"])

    def _open_about_dialog(self) -> None:
        rep = self.thermal_view.last_report
        hw_summary = (
            f"{rep.manufacturer} {rep.model} | {rep.cpu_name} | {rep.gpu_name} | {rep.total_ram_gb:.1f} GB RAM"
            if rep
            else "Escaneo en curso..."
        )
        dlg = AboutUpdaterDialog(
            lang=self.policy.config.language,
            theme_mode=self.policy.config.theme_mode,
            run_async=self._run_async,
            hardware_summary=hw_summary,
            parent=self,
        )
        dlg.exec()

    def _on_elevated_temps(self, cpu_c: float | None, nvme_c: float | None) -> None:
        self.telemetry_reader.set_elevated_temps(cpu_c, nvme_c)
        self._sample_telemetry()

    def _sync_active_task_indicators(self) -> None:
        self.overview_view.set_active_tasks(self._active_task_names)
        self.processes_view.set_active_tasks(self._active_task_names)

    def _run_async(self, fn, callback, task_label: str = "Tarea en segundo plano") -> None:
        worker = AsyncTask(fn)
        self._active_workers.append(worker)
        self._active_task_names.append(task_label)
        self._sync_active_task_indicators()

        def _cleanup_common() -> None:
            if worker in self._active_workers:
                self._active_workers.remove(worker)
            if task_label in self._active_task_names:
                self._active_task_names.remove(task_label)
            self._sync_active_task_indicators()

        def _cleanup_and_emit(result) -> None:
            _cleanup_common()
            callback(result)

        def _cleanup_on_err(err: str) -> None:
            _cleanup_common()
            self._set_status(f"Aviso: {err}")

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

    def _execute_ai_boost(self, actor: str) -> None:
        self.overview_view.boost_btn.setEnabled(False)
        self._set_status("Optimizando Working Set y EcoQoS...")

        def _work() -> dict[str, float | int]:
            return run_ai_boost(
                trim_heavy_apps=True,
                apply_ecoqos=self.policy.config.auto_ecoqos_background_browsers,
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
            if actor == "sre_auto":
                self.tray.showMessage("WinOptiAI Guardia SRE", msg)

        self._run_async(_work, _done, "AI Boost (RAM + EcoQoS)")

    def _tray_thermal(self, key: str) -> None:
        ok, msg = apply_thermal_profile(key)
        if ok:
            self.policy.config.active_thermal_profile = key
            self.policy.save_config()
            self.thermal_view._highlight_profile_button(key)
            self.policy.record_audit_event("tray", "Perfil termico", msg)
            self.overview_view.set_audit_rows(self.policy.read_recent_audit())
        self._set_status(msg)
        self.tray.showMessage("WinOptiAI Termica", msg)
