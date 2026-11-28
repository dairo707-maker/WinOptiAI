"""User Application Manager view: installed apps, last-used column, winget updates, safe uninstall."""

from __future__ import annotations

import time
from typing import Callable

from PySide6.QtCore import QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
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
    bulk_upgrade_skip_reason,
    check_app_updates_winget,
    running_app_processes,
    find_app_leftovers,
    list_installed_apps,
    uninstall_installed_app,
    upgrade_app_winget_elevated,
    upgrade_apps_winget,
)
from ...core.help_catalog import TOOLTIPS
from ...core.i18n import tr
from ...core.safety_guard import QuarantineVault
from ...core.sre_policy import SREPolicyEngine
from ...core.usage_telemetry import format_app_last_used
from ..app_icons import ICON_PX, app_icon, blank_icon, cached_app_icon
from ..svg_icons import load_svg_icon
from ..context_menu import copy_row_extra, copy_text, install_action_menu
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
        self._icon_queue: list[int] = []  # v0.6.5: iconos pendientes (se cargan por tandas)
        self._last_scan_ts = 0.0  # v0.6.6: hora del ultimo escaneo completo
        self._stale = False  # v0.6.6: el Vigia diario u otra accion pide refrescar
        self._upgrading = False
        self._updates_error = ""
        self._failed_apps: list[InstalledApp] = []
        self._status_cache: dict[str, tuple[str, str, str]] = {}

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

        self.upgrade_btn = QPushButton("Actualizar seleccionadas")
        set_button_role(self.upgrade_btn, ROLE_RESTORE)
        self.upgrade_btn.setToolTip(TOOLTIPS["apps_upgrade"])
        self.upgrade_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.upgrade_btn.clicked.connect(self._on_upgrade_selected)
        actions.addWidget(self.upgrade_btn)

        # v0.6.3: actualizar en lote (una por una, cancelable). Excluye entornos de desarrollo,
        # componentes del sistema y saltos de version mayor (ver bulk_upgrade_skip_reason).
        self.upgrade_all_btn = QPushButton("Actualizar todas")
        set_button_role(self.upgrade_all_btn, ROLE_RESTORE)
        self.upgrade_all_btn.setToolTip(
            "Actualiza con winget, una por una, todas las apps con nueva version. Omite entornos de "
            "desarrollo (Python, R, Node, .NET), componentes del sistema y saltos de version mayor: "
            "esas se actualizan a mano. Puedes cancelar entre una app y otra."
        )
        self.upgrade_all_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.upgrade_all_btn.clicked.connect(self._on_upgrade_all)
        actions.addWidget(self.upgrade_all_btn)

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

        self.retry_failed_btn = QPushButton("Reintentar fallidas")
        self.retry_failed_btn.setObjectName("GhostAction")
        self.retry_failed_btn.setToolTip("Reintentar las apps que fallaron (incluye opcion UAC si alguna pidio Administrador)")
        self.retry_failed_btn.setCursor(Qt.CursorShape.PointingHandCursor)
        self.retry_failed_btn.setVisible(False)
        self.retry_failed_btn.clicked.connect(self._on_retry_failed)
        sl.addWidget(self.retry_failed_btn)
        root.addWidget(summary)

        # Sortable Applications Table (manually resizable + horizontal scroll + persisted widths)
        self.apps_table = QTableWidget(0, 7)
        self.apps_table.setHorizontalHeaderLabels(
            ["ESTADO", "APLICACION", "VERSION", "NUEVA VERSION", "TAMANO", "ULTIMO USO", "EDITOR"]
        )
        configure_sortable_table(self.apps_table)
        self.apps_table.setSelectionMode(QTableWidget.SelectionMode.ExtendedSelection)
        self.apps_table.setIconSize(QSize(ICON_PX, ICON_PX))
        configure_interactive_columns(
            self.apps_table,
            [114, 290, 128, 136, 96, 138, 220],
            policy=self.policy,
            storage_key="apps_table",
        )
        root.addWidget(self.apps_table, stretch=1)
        # v0.6.5: clic derecho = mismas acciones del apartado
        install_action_menu(self.apps_table, extras=self._row_menu_extras)

    def apply_language_and_theme(self, lang: str, icon_inverted: str, theme_mode: str = "dark") -> None:
        self.lang = lang
        self.title_lbl.setText(tr("apps_title", lang))
        self.sub_lbl.setText(tr("apps_sub", lang))
        self.scan_btn.setIcon(load_svg_icon("apps", color=icon_inverted, size=14))
        self.sem_dot.set_tone(self.sem_dot._tone, theme_mode)
        self._render_apps()

    REFRESH_MAX_AGE_S = 30 * 60

    def mark_stale(self) -> None:
        """v0.6.6: pedir un escaneo nuevo la proxima vez que se abra la pestana."""
        self._stale = True

    def needs_refresh(self, now: float | None = None) -> bool:
        """Listado vacio, marcado como viejo o con mas de 30 min (y sin tareas en curso)."""
        if self._upgrading or not self.scan_btn.isEnabled() or self._checking_updates:
            return False
        if not self.apps or self._stale:
            return True
        return ((now or time.time()) - self._last_scan_ts) > self.REFRESH_MAX_AGE_S

    def refresh_apps(self) -> None:
        self.scan_btn.setEnabled(False)
        self.check_updates_btn.setEnabled(False)
        self.summary_lbl.setText("Escaneando aplicaciones instaladas y fechas reales de ultimo uso...")

        def _done(apps: list[InstalledApp]) -> None:
            self.scan_btn.setEnabled(True)
            self._last_scan_ts = time.time()
            self._stale = False
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
            self._restore_cached_statuses(apps)
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

    def _row_menu_extras(self):
        from ...core.win32_bridge import reveal_in_explorer

        selected = self._selected_apps()
        if not selected:
            return []
        upgradable = [a for a in selected if a.available_version and not a.protected_reason]
        busy = not self.upgrade_btn.isEnabled()
        if len(upgradable) == 1:
            upd_label = f"Actualizar a {upgradable[0].available_version}"
        else:
            upd_label = f"Actualizar {len(upgradable)} apps"
        app = selected[0]
        single = len(selected) == 1
        loc = (app.install_location or "").strip().strip('"')
        safe_url = app.upgrade_url if (app.upgrade_url or "").lower().startswith("https://") else ""
        return [
            (upd_label, self._on_upgrade_selected, bool(upgradable) and not busy),
            ("Abrir sitio oficial (HTTPS)", lambda u=safe_url: QDesktopServices.openUrl(QUrl(u)), single and bool(safe_url)),
            ("Desinstalar", self._on_uninstall_selected, single and not app.protected_reason),
            None,
            ("Abrir carpeta de instalacion", lambda: reveal_in_explorer(loc), single and bool(loc)),
            ("Copiar nombre", lambda: copy_text(", ".join(a.name for a in selected)), True),
            copy_row_extra(self.apps_table) if single else None,
        ]

    def _selected_apps(self) -> list[InstalledApp]:
        rows = sorted({idx.row() for idx in self.apps_table.selectedIndexes()})
        out: list[InstalledApp] = []
        for r in rows:
            it = self.apps_table.item(r, 0)
            if it is None:
                continue
            orig = it.data(Qt.ItemDataRole.UserRole + 1)
            if isinstance(orig, int) and 0 <= orig < len(self.apps):
                out.append(self.apps[orig])
        return out

    def _selected_app(self) -> InstalledApp | None:
        apps = self._selected_apps()
        return apps[0] if apps else None

    def _on_upgrade_selected(self) -> None:
        selected = self._selected_apps()
        if not selected:
            self.notify_cb("Selecciona una o varias aplicaciones de la tabla (Ctrl o Mayus para varias).")
            return
        blocked = [a for a in selected if a.protected_reason]
        targets = [a for a in selected if a.available_version and not a.protected_reason]
        if not targets:
            if blocked:
                self.notify_cb(f"Protegida: {blocked[0].protected_reason}")
            else:
                self.notify_cb("Primero usa 'Buscar Actualizaciones' o selecciona apps con nueva version.")
            return
        # Seleccion manual: la persona eligio estas apps, pero se avisa de los saltos mayores.
        warn = [a for a in targets if bulk_upgrade_skip_reason(a)]
        if warn:
            lines = "\n".join(f"- {a.name}: {bulk_upgrade_skip_reason(a)}" for a in warn[:8])
            ans = QMessageBox.question(
                self,
                "Confirmar actualizacion",
                f"Vas a actualizar {len(targets)} app(s). Revisa estas antes de continuar:\n\n{lines}\n\n"
                "Si un proyecto depende de esa version, podria dejar de funcionar. Continuar?",
            )
            if ans != QMessageBox.StandardButton.Yes:
                return
        if not self._confirm_apps_closed(targets):
            return
        self._run_upgrades(targets, "Actualizar apps seleccionadas")

    def _on_upgrade_all(self) -> None:
        candidates = [a for a in self.apps if a.available_version]
        if not candidates:
            self.notify_cb("No hay actualizaciones pendientes. Usa 'Buscar Actualizaciones' primero.")
            return
        targets = [a for a in candidates if not bulk_upgrade_skip_reason(a)]
        skipped = [a for a in candidates if bulk_upgrade_skip_reason(a)]
        if not targets:
            self.notify_cb(
                f"Las {len(skipped)} actualizaciones pendientes requieren revision manual "
                "(entornos de desarrollo o version mayor). Seleccionalas y usa 'Actualizar seleccionadas'."
            )
            return
        skipped_txt = ""
        if skipped:
            names = ", ".join(a.name for a in skipped[:6]) + ("..." if len(skipped) > 6 else "")
            skipped_txt = f"\n\nSe omiten {len(skipped)} para revisar a mano: {names}"
        ans = QMessageBox.question(
            self,
            "Actualizar todas",
            f"Se actualizaran {len(targets)} aplicaciones con winget, una por una.{skipped_txt}\n\n"
            "Windows puede pedir permiso de administrador en algunas. Cierra las apps que vayas a "
            "actualizar para evitar fallos. Continuar?",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return
        if not self._confirm_apps_closed(targets):
            return
        self._run_upgrades(targets, f"Actualizar {len(targets)} apps")

    def _confirm_apps_closed(self, targets: list[InstalledApp]) -> bool:
        """v0.6.4: con la app abierta el instalador falla o se queda esperando: pedir cerrarla antes."""
        open_apps = [(a, procs) for a in targets if (procs := running_app_processes(a))]
        if not open_apps:
            return True
        lines = "\n".join(f"- {a.name} ({', '.join(p[:3])})" for a, p in open_apps[:8])
        ans = QMessageBox.question(
            self,
            "Cerrar apps antes de actualizar",
            f"Estas apps estan abiertas y su instalador podria fallar o quedarse esperando:\n\n{lines}\n\n"
            "Guarda tu trabajo, cierralas y pulsa Si para continuar (No para volver).",
        )
        if ans != QMessageBox.StandardButton.Yes:
            return False
        still = [a.name for a, _p in open_apps if running_app_processes(a)]
        if still:
            self.notify_cb("Siguen abiertas: " + ", ".join(still[:4]) + ". Se intentara igual; si falla, cierralas y repite.")
        return True

    @staticmethod
    def _app_cache_key(app: InstalledApp) -> str:
        return (app.winget_id or app.name or "").strip().lower()

    def _restore_cached_statuses(self, apps: list[InstalledApp]) -> None:
        """Conserva estado diagnostico (SOLO EDITOR, 0x80073D28, TLS) entre re-escaneos."""
        for app in apps:
            key = self._app_cache_key(app)
            if not key or key not in self._status_cache:
                continue
            if not app.available_version:
                self._status_cache.pop(key, None)
                continue
            status, note, url = self._status_cache[key]
            app.upgrade_status = status
            app.upgrade_note = note
            if url and not app.upgrade_url:
                app.upgrade_url = url
        self._sync_failed_apps(apps)

    def _sync_failed_apps(self, apps: list[InstalledApp] | None = None) -> None:
        src = apps if apps is not None else self.apps
        retryable = ("needs_admin", "tls_error", "blocked", "failed")
        self._failed_apps = [
            a for a in src if a.available_version and a.upgrade_status in retryable
        ]
        self.retry_failed_btn.setVisible(bool(self._failed_apps) and not self._upgrading)
        if self._failed_apps:
            self.retry_failed_btn.setText(f"Reintentar fallidas ({len(self._failed_apps)})")

    def _run_elevated_upgrades(self, admin_apps: list[InstalledApp]) -> None:
        if not admin_apps:
            return
        self._upgrading = True
        self.retry_failed_btn.setVisible(False)

        def _work() -> list[tuple[InstalledApp, bool, str]]:
            return [(a, *upgrade_app_winget_elevated(a)) for a in admin_apps]

        def _done(res: list[tuple[InstalledApp, bool, str]]) -> None:
            self._upgrading = False
            for a, good, m in res:
                self.policy.record_audit_event("usuario", "Actualizar App (UAC)" if good else "Actualizar App (fallo)", m)
                if good:
                    self._status_cache.pop(self._app_cache_key(a), None)
            launched = sum(1 for _a, good, _m in res if good)
            self.notify_cb(f"{launched}/{len(res)} actualizacion(es) lanzada(s) con permisos UAC.")
            self._sync_failed_apps()
            self._render_apps()
            if launched:
                QTimer.singleShot(2500, self.refresh_apps)

        def _err(_e: str) -> None:
            self._upgrading = False
            self._sync_failed_apps()

        self.run_async(_work, _done, "Actualizar apps (UAC)", on_error=_err)

    def _on_retry_failed(self) -> None:
        self._sync_failed_apps()
        if not self._failed_apps:
            self.retry_failed_btn.setVisible(False)
            self.notify_cb("No hay actualizaciones fallidas pendientes de reintento.")
            return
        admin_apps = [a for a in self._failed_apps if a.upgrade_status == "needs_admin"]
        normal_apps = [a for a in self._failed_apps if a.upgrade_status != "needs_admin"]
        if admin_apps:
            names = ", ".join(a.name for a in admin_apps[:4])
            ans = QMessageBox.question(
                self,
                "Permisos de Administrador requeridos",
                f"Estas aplicaciones pidieron permisos de Administrador (0x80073D28): {names}.\n\n"
                "Deseas ejecutar su actualizacion con permisos elevados (UAC)?",
            )
            if ans == QMessageBox.StandardButton.Yes:
                self._run_elevated_upgrades(admin_apps)
        if normal_apps and self._confirm_apps_closed(normal_apps):
            self._run_upgrades(normal_apps, f"Reintentar {len(normal_apps)} apps fallidas")

    def _run_upgrades(self, targets: list[InstalledApp], label: str) -> None:
        self._upgrading = True
        self.upgrade_btn.setEnabled(False)
        self.upgrade_all_btn.setEnabled(False)
        self.retry_failed_btn.setVisible(False)
        self.summary_lbl.setText(f"Actualizando {len(targets)} aplicacion(es) con winget...")

        def _work(progress_cb=None, controller=None):
            return upgrade_apps_winget(targets, progress_cb=progress_cb, controller=controller)

        def _done(results) -> None:
            self.upgrade_btn.setEnabled(True)
            self.upgrade_all_btn.setEnabled(True)
            ok = [a for a, good, _m in results if good]
            failed = [(a, m) for a, good, m in results if not good]
            self._upgrading = False
            for a, good, m in results:
                # v0.6.6: tambien los fallos quedan en la auditoria, con su motivo
                self.policy.record_audit_event("usuario", "Actualizar App" if good else "Actualizar App (fallo)", m)
                key = self._app_cache_key(a)
                if good:
                    self._status_cache.pop(key, None)
                elif key and a.upgrade_status:
                    self._status_cache[key] = (a.upgrade_status, a.upgrade_note, a.upgrade_url)
            self._sync_failed_apps()
            msg = f"{len(ok)} de {len(targets)} aplicacion(es) actualizadas."
            if len(results) < len(targets):
                msg += f" Cancelado: {len(targets) - len(results)} sin intentar."
            if failed:
                msg += " Fallaron: " + "; ".join(f"{a.name} ({m[:70]})" for a, m in failed[:3])
            self.notify_cb(msg)
            self.summary_lbl.setText(msg)
            self._render_apps()
            admin_failed = [a for a, _m in failed if a.upgrade_status == "needs_admin"]
            if admin_failed:
                names = ", ".join(a.name for a in admin_failed[:4])
                ans = QMessageBox.question(
                    self,
                    "Permisos de Administrador requeridos",
                    f"{len(admin_failed)} aplicacion(es) requieren Administrador ({names}).\n\n"
                    "Deseas lanzarlas ahora con UAC?",
                )
                if ans == QMessageBox.StandardButton.Yes:
                    self._run_elevated_upgrades(admin_failed)
                    return
            # v0.6.6: verificar con Windows/winget la version que de verdad quedo instalada
            if results:
                QTimer.singleShot(1500, self.refresh_apps)

        def _err(_e: str) -> None:
            self._upgrading = False
            self.upgrade_btn.setEnabled(True)
            self.upgrade_all_btn.setEnabled(True)
            self._sync_failed_apps()

        self.run_async(_work, _done, label, on_error=_err)

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

    def _load_icon_batch(self) -> None:
        """Cargar unos pocos iconos por vuelta del bucle de eventos: la tabla nunca se congela."""
        if not self._icon_queue:
            return
        dpr = float(self.devicePixelRatioF() or 1.0)
        batch, self._icon_queue = self._icon_queue[:6], self._icon_queue[6:]
        loaded: dict[int, object] = {}
        for idx in batch:
            if 0 <= idx < len(self.apps):
                loaded[idx] = app_icon(self.apps[idx], dpr)
        for r in range(self.apps_table.rowCount()):
            c0 = self.apps_table.item(r, 0)
            c1 = self.apps_table.item(r, 1)
            if c0 is None or c1 is None:
                continue
            idx = c0.data(Qt.ItemDataRole.UserRole + 1)
            if idx in loaded:
                c1.setIcon(loaded[idx])
        if self._icon_queue:
            QTimer.singleShot(10, self._load_icon_batch)

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
        dpr = float(self.devicePixelRatioF() or 1.0)
        pending: list[int] = []
        for r, (orig_idx, app) in enumerate(visible):
            eff_ts = app.last_used_ts if app.last_used_ts > 0 else app.install_date_ts
            is_stale = eff_ts > 0 and eff_ts <= stale_cutoff
            if app.upgrade_status == "editor_only":
                state_txt, tone = "SOLO EDITOR", "neutral"
            elif app.available_version:
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
            if app.upgrade_note:
                c0.setToolTip(app.upgrade_note)
            self.apps_table.setItem(r, 0, c0)
            name_item = QTableWidgetItem(app.name)
            if app.upgrade_note:
                name_item.setToolTip(f"{app.name}\n{app.upgrade_note}")
            cached = cached_app_icon(app, dpr)  # v0.6.5: icono real de la app, sutil
            name_item.setIcon(cached or blank_icon())
            if cached is None:
                pending.append(orig_idx)
            self.apps_table.setItem(r, 1, name_item)
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
        self._icon_queue = pending
        if pending:
            QTimer.singleShot(0, self._load_icon_batch)
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
