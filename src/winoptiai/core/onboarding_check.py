"""Fast read-only system verification suite for new WinOptiAI installations."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import os
from pathlib import Path
import platform
from typing import Callable

import psutil

from ..apps.app_manager import is_winget_available
from ..apps.startup_manager import scan_startup_items
from ..storage.onedrive_optimizer import discover_onedrive_roots
from ..thermal_bios.bios_auditor import HardwareAuditReport, run_hardware_bios_audit
from ..thermal_bios.thermal_controller import get_active_power_scheme
from .safety_guard import QuarantineVault
from .sre_policy import SREPolicyEngine, recommended_ram_threshold_gb
from .telemetry import PdhTelemetryReader
from .win32_bridge import IS_WINDOWS, has_windows_reboot_pending


@dataclass(slots=True)
class QuickCheckItem:
    """Single verified diagnostic check displayed in the new-PC onboarding summary."""

    category: str
    status: str       # "OK" | "AVISO" | "INFO"
    summary: str
    recommendation: str = ""


@dataclass(slots=True)
class QuickCheckReport:
    """Complete read-only diagnostic snapshot for a newly installed PC."""

    checked_at: str
    device_line: str
    recommended_threshold_gb: float
    items: list[QuickCheckItem] = field(default_factory=list)
    audit_report: HardwareAuditReport | None = None


def _shallow_temp_estimate(max_entries: int = 1200) -> tuple[int, int]:
    """Quick bounded 1-level scan of user %TEMP% without modifying anything."""
    temp_dir = Path(os.environ.get("TEMP", ""))
    if not temp_dir.exists():
        return 0, 0
    count = 0
    total_bytes = 0
    try:
        with os.scandir(temp_dir) as it:
            for entry in it:
                count += 1
                if count > max_entries:
                    break
                try:
                    if entry.is_file(follow_symlinks=False):
                        total_bytes += entry.stat(follow_symlinks=False).st_size
                except OSError:
                    continue
    except OSError:
        pass
    return count, total_bytes


def run_new_pc_quick_check(
    policy: SREPolicyEngine | None = None,
    vault: QuarantineVault | None = None,
    progress_cb: Callable[[int, str], None] | None = None,
) -> QuickCheckReport:
    """Execute a safe ~3-5s hardware, telemetry, storage, and OS readiness verification."""
    items: list[QuickCheckItem] = []

    if progress_cb:
        progress_cb(12, "Verificando CPU, RAM y umbral SRE...")
    vm = psutil.virtual_memory()
    total_ram_gb = round(vm.total / (1024**3), 1)
    free_ram_gb = round(vm.available / (1024**3), 2)
    rec_thresh = recommended_ram_threshold_gb()
    ram_status = "AVISO" if free_ram_gb < rec_thresh else "OK"
    items.append(
        QuickCheckItem(
            category="Memoria y Guardia SRE",
            status=ram_status,
            summary=(
                f"RAM total {total_ram_gb:.1f} GB | Libre ahora: {free_ram_gb:.2f} GB "
                f"| Umbral SRE calibrado: {rec_thresh:.1f} GB"
            ),
            recommendation="Ejecuta AI Boost si la RAM libre esta ajustada." if ram_status == "AVISO" else "",
        )
    )

    if progress_cb:
        progress_cb(32, "Probando sensores en tiempo real (PDH y Energia)...")
    reader = PdhTelemetryReader()
    live = reader.sample()
    _guid, plan_name = get_active_power_scheme()
    pdh_ok = live.cpu_freq_mhz > 0 or live.cpu_utility_pct >= 0.0
    items.append(
        QuickCheckItem(
            category="Telemetria PDH y Energia",
            status="OK" if pdh_ok else "AVISO",
            summary=(
                f"CPU uso {live.cpu_utility_pct:.0f}% @ {live.cpu_freq_mhz / 1000.0:.2f} GHz "
                f"| Turbo {live.cpu_turbo_pct:.0f}% | Plan: {plan_name}"
            ),
            recommendation="Usa 'Termica y BIOS' para activar Frio/Silencioso o IA Local.",
        )
    )

    if progress_cb:
        progress_cb(55, "Consultando hardware, BIOS/OEM y S.M.A.R.T....")
    audit = run_hardware_bios_audit()
    disk_pct_free = (
        round((audit.disk_free_gb / audit.disk_total_gb) * 100.0, 1)
        if audit.disk_total_gb > 0
        else 0.0
    )
    disk_status = "AVISO" if (disk_pct_free < 12.0 or audit.disk_events_count > 0) else "OK"
    items.append(
        QuickCheckItem(
            category="Disco, S.M.A.R.T. y Eventos 14d",
            status=disk_status,
            summary=(
                f"{audit.nvme_model} [{audit.media_type} - {audit.nvme_health}] | "
                f"Libre C: {audit.disk_free_gb:.1f}/{audit.disk_total_gb:.1f} GB ({disk_pct_free}%) | "
                f"Evt14d: {audit.disk_events_count}"
            ),
            recommendation=(
                "Espacio bajo o eventos recientes detectados; revisa Temporales o CHKDSK."
                if disk_status == "AVISO"
                else ""
            ),
        )
    )

    reboot_pending = has_windows_reboot_pending()
    sec_status = "AVISO" if reboot_pending else "OK"
    items.append(
        QuickCheckItem(
            category="BIOS/OEM, Seguridad y Reinicio",
            status=sec_status,
            summary=(
                f"BIOS {audit.bios_version} ({audit.bios_date}, {audit.oem_tool or audit.manufacturer}) | "
                f"{audit.security_posture}"
                + (" | REINICIO WINDOWS PENDIENTE" if reboot_pending else "")
            ),
            recommendation=(
                "Hay actualizaciones pendientes de reinicio en Windows: reinicia antes de usar DISM/SFC."
                if reboot_pending
                else ""
            ),
        )
    )

    if progress_cb:
        progress_cb(82, "Inspeccionando OneDrive local y Boveda de Cuarentena...")
    od_roots = discover_onedrive_roots()
    vault_items = len(vault.list_items()) if vault is not None else 0
    temp_cnt, temp_bytes = _shallow_temp_estimate()
    od_desc = (
        ", ".join(f"{r.label} ({r.path.name})" for r in od_roots)
        if od_roots
        else "No detectado"
    )
    temp_mb = round(temp_bytes / (1024 * 1024), 1)
    items.append(
        QuickCheckItem(
            category="Almacenamiento, OneDrive y Boveda",
            status="INFO",
            summary=(
                f"OneDrive local: {od_desc} | Muestra rapida %TEMP%: {temp_cnt}+ entradas ({temp_mb:.1f} MB nivel 1) "
                f"| Elementos en Boveda: {vault_items}"
            ),
            recommendation="Usa Almacenamiento > Temporales o Arbol para un analisis completo.",
        )
    )

    if progress_cb:
        progress_cb(90, "Evaluando winget y programas de inicio de Windows...")
    try:
        winget_ok = is_winget_available()
        startup_items = scan_startup_items()
        enabled_cnt = sum(1 for it in startup_items if it.enabled)
        sug_cnt = sum(
            1 for it in startup_items if it.enabled and it.recommendation in ("PAUSAR", "DESACTIVAR")
        )
        app_status = "AVISO" if (sug_cnt > 0 or not winget_ok) else "OK"
        app_rec = (
            "Abre 'Inicio Windows' para pausar o desactivar entradas sugeridas de arranque."
            if sug_cnt > 0
            else ("Instala 'Instalador de aplicacion' (winget) para actualizar software en 1 clic." if not winget_ok else "")
        )
        items.append(
            QuickCheckItem(
                category="Aplicaciones e Inicio de Windows",
                status=app_status,
                summary=(
                    f"winget: {'Disponible' if winget_ok else 'No detectado'} | "
                    f"Inicio activo: {enabled_cnt}/{len(startup_items)} apps | "
                    f"Sugeridas pausar/desactivar: {sug_cnt}"
                ),
                recommendation=app_rec,
            )
        )
    except Exception as exc:  # noqa: BLE001
        items.append(
            QuickCheckItem(
                category="Aplicaciones e Inicio de Windows",
                status="INFO",
                summary=f"Verificacion parcial de Aplicaciones / Inicio: {exc}",
                recommendation="Revisa manualmente las pestanas 'Aplicaciones' e 'Inicio Windows'.",
            )
        )

    device_line = (
        f"{audit.manufacturer} {audit.model} | {audit.cpu_name} | "
        f"{audit.gpu_name} | {platform.system()} {platform.release()}"
    )
    if policy is not None:
        policy.config.ram_threshold_gb = rec_thresh
        policy.config.last_quick_check_at = datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S")
        policy.save_config()

    if progress_cb:
        progress_cb(100, "Prueba rapida del equipo completada")

    return QuickCheckReport(
        checked_at=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
        device_line=device_line,
        recommended_threshold_gb=rec_thresh,
        items=items,
        audit_report=audit,
    )
