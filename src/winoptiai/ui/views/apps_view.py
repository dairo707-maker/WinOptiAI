"""User Application Manager view: installed apps, last-used column, winget updates, safe uninstall."""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ...apps.app_manager import (
    InstalledApp,
    check_app_updates_winget,
    find_app_leftovers,
    list_installed_apps,
    uninstall_installed_app,
    upgrade_app_winget,
)
from ...core.help_catalog import TOOLTIPS
from ...core.i18n import tr
from ...core.safety_guard import QuarantineVault
from ...core.sre_policy import SREPolicyEngine
from ...core.usage_telemetry import format_app_last_used
from ..svg_icons import load_svg_icon
from ..theme import format_bytes
from ..widgets import (
    ROLE_RESTORE,
    ROLE_RISK,
    FlowLayout,
    GlassPanel,
    NumericTableItem,
    SectionBenefitStrip,
    SemaphoreDot,
    apply_table_tooltips,
    configure_interactive_columns,
    configure_sortable_table,
    semaphore_hex,
    set_button_role,
)


class AppsView(QWidget):
    """Manage user applications: inspect last use, update via winget, or safely uninstall."""

    summary_changed = Signal(str, str)  # (semaphore_text, tone)

    def __init__(
        self,
        vault: QuarantineVault,
        policy: SREPolicyEngine,
        run_async: Callable,
        notify_cb: Callable[[str], None],
        lang: str = "es",
        parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.vault = vault
        self.policy = policy
        self.run_async = run_async
        self.notify_cb = notify_cb
        self.lang = lang
        self.apps: list[InstalledApp] = []
        self._updates_checked = False
        self._checking_updates = False
        self._updates_error = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(24, 18, 24, 18)
        root.setSpacing(10)

        header = QHBoxLayout()
        tbox = QVBoxLayout()
        tbox.setSpacing(2)
        self.title_lbl = QLabel(tr("apps_title", lang))
        self.title_lbl.setObjectName("PageTitle")
        self.sub_lbl = QLabel(tr("apps_sub", lang))
        self.sub_lbl.setObjectName("PageSubtitle")
        self.sub_lbl.setWordWrap(True)
        tbox.addWidget(self.title_lbl)
        tbox.addWidget(self.sub_lbl)
        header.addLayout(tbox, stretch=1)

        self.scan_btn = QPushButton(" Escanear Aplicaciones")
        self.scan_btn.setObjectName("PrimaryAction")
        self.scan_btn.setIcon(load_svg_icon("apps", color="#0A0F1D", size=14))
        self.scan_btn.setToolTip(TOOLTIPS["apps_scan"])
        self.scan_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.scan_btn.clicked.connect(self.refresh_apps)
        header.addWidget(self.scan_btn)
        root.addLayout(header)

        self.benefit_strip = SectionBenefitStrip("apps")
        root.addWidget(self.benefit_strip)

        # Actions bar (FlowLayout so buttons wrap cleanly at 980x650)
        actions = FlowLayout(spacing=6)
        self.check_updates_btn = QPushButton("Buscar Actualizaciones")
        self.check_updates_btn.setObjectName("GhostAction")
        self.check_updates_btn.setToolTip(TOOLTIPS["apps_check_updates"])
        self.check_updates_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.check_updates_btn.clicked.connect(self._on_check_updates)
        actions.addWidget(self.check_updates_btn)

        self.upgrade_btn = QPushButton("Actualizar App")
        set_button_role(self.upgrade_btn, ROLE_RESTORE)
        self.upgrade_btn.setToolTip(TOOLTIPS["apps_upgrade"])
        self.upgrade_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.upgrade_btn.clicked.connect(self._on_upgrade_selected)
        actions.addWidget(self.upgrade_btn)

        self.uninstall_btn = QPushButton("Desinstalar")
        set_button_role(self.uninstall_btn, ROLE_RISK)
        self.uninstall_btn.setToolTip(TOOLTIPS["apps_uninstall"])
        self.uninstall_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.uninstall_btn.clicked.connect(self._on_uninstall_selected)
        actions.addWidget(self.uninstall_btn)

        self.filter_combo = QComboBox()
        self.filter_combo.addItem("Todas", "all")
        self.filter_combo.addItem("Con actualizacion", "updates")
        self.filter_combo.addItem("Sin uso > 30 dias", "stale")
        self.filter_combo.currentIndexChanged.connect(lambda _i: self._render_apps())
        actions.addWidget(self.filter_combo)

        self.search_input = QLineEdit()
        self.search_input.setPlaceholderText("Filtrar app o editor...")
        self.search_input.setMinimumWidth(160)
        self.search_input.textChanged.connect(lambda _t: self._render_apps())
        actions.addWidget(self.search_input)
        root.addLayout(actions)

        # Summary bar with Semaphore
        summary = GlassPanel()
        sl = QHBoxLayout(summary)
        sl.setContentsMargins(12, 8, 12, 8)
        sl.setSpacing(8)
        self.sem_dot = SemaphoreDot("neutral", self.policy.config.theme_mode)
        sl.addWidget(self.sem_dot)
        self.summary_lbl = QLabel("Haz clic en 'Escanear Aplicaciones' para inventariar software y uso real.")
        self.summary_lbl.setObjectName("BodyText")
        self.summary_lbl.setWordWrap(True)
        sl.addWidget(self.summary_lbl, stretch=1)
        root.addWidget(summary)

        # Sortable Applications Table (manually resizable + horizontal scroll + persisted widths)
        self.apps_table = QTableWidget(0, 7)
        self.apps_table.setHorizontalHeaderLabels(
            ["ESTADO", "APLICACION", "VERSION", "NUEVA VERSION", "TAMANO", "ULTIMO USO", "EDITOR"]
        )
        configure_sortable_table(self.apps_table)
        self.apps_table.setSelectionMode(QTableWidget.SelectionMode.SingleSelection)
        configure_interactive_columns(
            self.apps_table,
            [114, 290, 128, 136, 96, 138, 220],
            policy=self.policy,
            storage_key="apps_table",
        )
        root.addWidget(self.apps_table, stretch=1)

    def apply_language_and_theme(self, lang: str, icon_inverted: str, theme_mode: str = "dark") -> None:
        self.lang = lang
        self.title_lbl.setText(tr("apps_title", lang))
        self.sub_lbl.setText(tr("apps_sub", lang))
        self.scan_btn.setIcon(load_svg_icon("apps", color=icon_inverted, size=14))
        self.sem_dot.set_tone(self.sem_dot._tone, theme_mode)
        self._render_apps()

    def refresh_apps(self) -> None:
        self.scan_btn.setEnabled(False)
        self.check_updates_btn.setEnabled(False)
        self.summary_lbl.setText("Escaneando aplicaciones instaladas y fechas reales de ultimo uso...")

        def _done(apps: list[InstalledApp]) -> None:
            self.scan_btn.setEnabled(True)
            self.apps = apps
            self._updates_checked = False
            self._updates_error = ""
            if self.apps:
                self._on_check_updates(auto_chained=True)
            else:
                self.check_updates_btn.setEnabled(True)
                self._render_apps()

        def _err(_msg: str) -> None:
            self.scan_btn.setEnabled(True)
            self.check_updates_btn.setEnabled(True)

        self.run_async(
            list_installed_apps,
            _done,
            "Escaneo aplicaciones",
            notify_on_complete=False,
            on_error=_err,
        )

    def _on_check_updates(self, _checked: bool = False, *, auto_chained: bool = False) -> None:
        if not self.apps:
            self.refresh_apps()
            return
        self._checking_updates = True
        self._updates_error = ""
        self.check_updates_btn.setEnabled(False)
        self._render_apps()
        self.summary_lbl.setText(
            f"{len(self.apps)} aplicaciones inventariadas — consultando nuevas versiones en winget..."
        )
        snapshot = list(self.apps)

        def _work(progress_cb=None) -> tuple[list[InstalledApp], int, str]:
            return check_app_updates_winget(snapshot, progress_cb=progress_cb)

        def _done(res: tuple[list[InstalledApp], int, str]) -> None:
            self._checking_updates = False
            self.check_updates_btn.setEnabled(True)
            apps, _count, msg = res
            self.apps = apps
            ok_winget = not msg.startswith(("winget no esta disponible", "No se pudo consultar"))
            self._updates_checked = ok_winget
            self._updates_error = "" if ok_winget else msg
            self._render_apps()
            if not ok_winget:
                self.summary_lbl.setText(f"{self.summary_lbl.text()}  |  {msg}")
            if not auto_chained:
                self.notify_cb(msg)

        def _err(err_msg: str) -> None:
            self._checking_updates = False
            self.check_updates_btn.setEnabled(True)
            self._updates_checked = False
            self._updates_error = err_msg or "Error consultando winget."
            self._render_apps()

        self.run_async(
            _work,
            _done,
            "Buscar actualizaciones de apps",
            notify_on_complete=False,
            on_error=_err,
        )

    def _selected_app(self) -> InstalledApp | None:
        rows = sorted({idx.row() for idx in self.apps_table.selectedIndexes()})
        if not rows:
            return None
        it = self.apps_table.item(rows[0], 0)
        if it is None:
            return None
        orig = it.data(Qt.ItemDataRole.UserRole + 1)
        if isinstance(orig, int) and 0 <= orig < len(self.apps):
            return self.apps[orig]
        return None

    def _on_upgrade_selected(self) -> None:
        app = self._selected_app()
        if app is None:
            self.notify_cb("Selecciona primero una aplicacion de la tabla.")
            return
        if app.protected_reason:
            self.notify_cb(f"Protegida: {app.protected_reason}")
            return
        if not app.available_version:
            self.notify_cb("Primero usa 'Buscar Actualizaciones' o selecciona una app con nueva version.")
            return

        self.upgrade_btn.setEnabled(False)
        self.summary_lbl.setText(f"Actualizando {app.name} a {app.available_version}...")

        def _work(progress_cb=None) -> tuple[bool, str]:
            return upgrade_app_winget(app, progress_cb=progress_cb)

        def _done(res: tuple[bool, str]) -> None:
            self.upgrade_btn.setEnabled(True)
            ok, msg = res
            if ok:
                app.version = app.available_version or app.version
                app.available_version = ""
                self.policy.record_audit_event("usuario", "Actualizar App", msg)
            self.notify_cb(msg)
            self._render_apps()

        self.run_async(
            _work,
            _done,
            f"Actualizar: {app.name}",
            on_error=lambda _e: self.upgrade_btn.setEnabled(True),
        )

    def _on_uninstall_selected(self) -> None:
        app = self._selected_app()
        if app is None:
            self.notify_cb("Selecciona la aplicacion que deseas desinstalar.")
            return
        if app.protected_reason:
            QMessageBox.information(
                self,
                "Aplicacion protegida",
                f"No se desinstala '{app.name}' porque es {app.protected_reason}.",
            )
            return

        reply = QMessageBox.question(
            self,
            "Confirmar desinstalacion",
            f"Deseas desinstalar '{app.name}' ({app.version})?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        self.uninstall_btn.setEnabled(False)
        self.summary_lbl.setText(f"Desinstalando {app.name}...")

        def _work(progress_cb=None) -> tuple[bool, str, list]:
            ok, msg = uninstall_installed_app(app, progress_cb=progress_cb)
            leftovers = find_app_leftovers(app) if ok else []
            return ok, msg, leftovers

        def _done(res: tuple[bool, str, list]) -> None:
            self.uninstall_btn.setEnabled(True)
            ok, msg, leftovers = res
            self.notify_cb(msg)
            if ok:
                self.policy.record_audit_event("usuario", "Desinstalar App", msg)
                self.apps = [a for a in self.apps if a is not app]
                self._render_apps()
                if leftovers:
                    names = "\n".join(f"- {p}" for p in leftovers[:6])
                    ans = QMessageBox.question(
                        self,
                        "Residuos detectados",
                        f"Se encontraron {len(leftovers)} carpeta(s) residuales en AppData:\n{names}\n\n"
                        "Deseas enviarlas de forma reversible a la Boveda de Cuarentena?",
                        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                        QMessageBox.StandardButton.Yes,
                    )
                    if ans == QMessageBox.StandardButton.Yes:
                        self.vault.quarantine_many([(p, f"Residuo:{app.name}") for p in leftovers])
                        self.notify_cb(f"{len(leftovers)} residuo(s) de {app.name} movidos a Cuarentena.")

        self.run_async(
            _work,
            _done,
            f"Desinstalar: {app.name}",
            on_error=lambda _e: self.uninstall_btn.setEnabled(True),
        )

    def _render_apps(self) -> None:
        now = time.time()
        stale_cutoff = now - 30 * 86400
        flt = str(self.filter_combo.currentData() or "all")
        q = (self.search_input.text() or "").strip().lower()
        mode = self.policy.config.theme_mode

        visible: list[tuple[int, InstalledApp]] = []
        updates_cnt = 0
        stale_cnt = 0
        for idx, app in enumerate(self.apps):
            eff_ts = app.last_used_ts if app.last_used_ts > 0 else app.install_date_ts
            is_stale = eff_ts > 0 and eff_ts <= stale_cutoff
            if app.available_version:
                updates_cnt += 1
            if is_stale:
                stale_cnt += 1
            if flt == "updates" and not app.available_version:
                continue
            if flt == "stale" and not (eff_ts <= stale_cutoff):
                continue
            if q and q not in app.name.lower() and q not in app.publisher.lower():
                continue
            visible.append((idx, app))

        self.apps_table.setSortingEnabled(False)
        self.apps_table.setRowCount(len(visible))
        for r, (orig_idx, app) in enumerate(visible):
            eff_ts = app.last_used_ts if app.last_used_ts > 0 else app.install_date_ts
            is_stale = eff_ts > 0 and eff_ts <= stale_cutoff
            if app.available_version:
                state_txt, tone = "ACTUALIZAR", "warn"
            elif app.protected_reason:
                state_txt, tone = "PROTEGIDA", "neutral"
            elif self._checking_updates:
                state_txt, tone = "REVISANDO", "active"
            elif is_stale:
                state_txt, tone = "SIN USO", "risk"
            elif not self._updates_checked:
                state_txt, tone = "SIN REVISAR", "neutral"
            else:
                state_txt, tone = "AL DIA", "ok"

            c0 = QTableWidgetItem(state_txt)
            c0.setData(Qt.ItemDataRole.UserRole + 1, orig_idx)
            c0.setForeground(QColor(semaphore_hex(tone, mode)))
            self.apps_table.setItem(r, 0, c0)
            self.apps_table.setItem(r, 1, QTableWidgetItem(app.name))
            self.apps_table.setItem(r, 2, QTableWidgetItem(app.version))

            if app.available_version:
                upd_item = QTableWidgetItem(app.available_version)
                upd_item.setForeground(QColor(semaphore_hex("warn", mode)))
            elif self._checking_updates:
                upd_item = QTableWidgetItem("Consultando...")
                upd_item.setForeground(QColor(semaphore_hex("active", mode)))
            else:
                upd_item = QTableWidgetItem("--")
            self.apps_table.setItem(r, 3, upd_item)

            self.apps_table.setItem(
                r,
                4,
                NumericTableItem(format_bytes(app.size_bytes) if app.size_bytes > 0 else "--", app.size_bytes),
            )
            used_txt = format_app_last_used(app.last_used_ts, app.install_date_ts, now)
            used_item = NumericTableItem(used_txt, eff_ts)
            if app.last_used_ts > 0:
                used_item.setToolTip(f"{used_txt} (ejecucion real registrada en Windows)")
            elif app.install_date_ts > 0:
                used_item.setToolTip(f"{used_txt} (sin ejecucion reciente; fecha de instalacion en Registro)")
            else:
                used_item.setToolTip("Sin registro de ejecucion ni fecha de instalacion")
            self.apps_table.setItem(r, 5, used_item)
            self.apps_table.setItem(r, 6, QTableWidgetItem(app.publisher or "--"))
        apply_table_tooltips(self.apps_table)
        self.apps_table.setSortingEnabled(True)

        if self.apps:
            extra_err = f"  |  {self._updates_error}" if self._updates_error and not self._checking_updates else ""
            self.summary_lbl.setText(
                f"Mostrando {len(visible)} de {len(self.apps)} apps  |  "
                f"Actualizaciones: {updates_cnt}  |  Sin uso >30d: {stale_cnt}{extra_err}"
            )
            sem_tone = (
                "warn"
                if updates_cnt > 0
                else ("active" if self._checking_updates else ("risk" if stale_cnt > 5 else ("ok" if self._updates_checked else "neutral")))
            )
            sem_txt = (
                f"{updates_cnt} upd"
                if updates_cnt > 0
                else ("Revisando..." if self._checking_updates else ("Al dia" if self._updates_checked else f"{len(self.apps)} apps"))
            )
            self.sem_dot.set_tone(sem_tone, mode)
            self.summary_changed.emit(sem_txt, sem_tone)
        else:
            self.sem_dot.set_tone("neutral", mode)
