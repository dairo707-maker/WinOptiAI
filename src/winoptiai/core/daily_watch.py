"""Vigia diario (v0.6.3): revisa en horarios fijos si hay algo que atender y avisa con un resumen.

Solo LEE: consulta actualizaciones de apps (winget) y temporales seguros acumulados. Nunca
actualiza, borra ni mueve nada por su cuenta; la persona decide desde la pestana indicada.

Horarios por defecto 09:00, 14:00 y 19:00 (``SREPolicyConfig.daily_watch_hours``). Si el equipo
estaba apagado o suspendido a esa hora, el aviso sale en cuanto vuelve (una sola vez por horario).
Un resumen identico al anterior no se repite dentro de ``REPEAT_AFTER_S``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
import hashlib
from typing import Callable

DEFAULT_WATCH_HOURS: tuple[int, ...] = (9, 14, 19)
JUNK_MIN_BYTES = 300 * 1024 * 1024  # avisar desde 300 MB de temporales seguros
REPEAT_AFTER_S = 20 * 3600  # el mismo resumen no se repite antes de 20 h

TAB_STORAGE = 1
TAB_APPS = 4


@dataclass(slots=True)
class WatchFindings:
    """Resultado de una revision del vigia (solo lectura)."""

    app_updates: list[str] = field(default_factory=list)  # nombres de apps con nueva version
    manual_updates: int = 0  # entornos/saltos mayores que conviene actualizar a mano
    junk_bytes: int = 0
    junk_files: int = 0
    errors: list[str] = field(default_factory=list)


def sanitize_hours(raw: object) -> list[int]:
    """Horas validas 0-23, ordenadas y sin repetir; vacio o invalido -> horario por defecto."""
    out: set[int] = set()
    if isinstance(raw, (list, tuple)):
        for h in raw:
            if isinstance(h, bool):
                continue
            if isinstance(h, (int, float)) and 0 <= int(h) <= 23:
                out.add(int(h))
    return sorted(out) if out else list(DEFAULT_WATCH_HOURS)


def due_slot(now: datetime, hours: object, last_slot: str) -> str | None:
    """Devuelve el identificador 'YYYY-MM-DD@HH' del horario pendiente, o None si no toca.

    Toca el horario mas reciente de HOY cuya hora ya paso y que aun no se atendio. Antes del
    primer horario del dia no hay nada pendiente (no se arrastran avisos de ayer).
    """
    passed = [h for h in sanitize_hours(hours) if h <= now.hour]
    if not passed:
        return None
    slot = f"{now.strftime('%Y-%m-%d')}@{max(passed):02d}"
    return None if slot == last_slot else slot


def _fmt_size(num: int) -> str:
    gb = num / (1024**3)
    return f"{gb:.2f} GB" if gb >= 1 else f"{num / (1024**2):.0f} MB"


def build_digest(findings: WatchFindings, junk_min_bytes: int = JUNK_MIN_BYTES) -> list[dict]:
    """Convierte hallazgos en avisos claros (titulo, detalle, pestana destino). Vacio = todo en orden."""
    items: list[dict] = []
    n_upd = len(findings.app_updates)
    if n_upd:
        sample = ", ".join(findings.app_updates[:4]) + ("..." if n_upd > 4 else "")
        extra = f" Otras {findings.manual_updates} conviene actualizarlas a mano." if findings.manual_updates else ""
        items.append(
            {
                "key": "updates",
                "title": f"{n_upd} aplicacion(es) con actualizacion",
                "detail": f"{sample}. Abre Aplicaciones y usa 'Actualizar todas'.{extra}",
                "action_tab": TAB_APPS,
            }
        )
    elif findings.manual_updates:
        items.append(
            {
                "key": "updates",
                "title": f"{findings.manual_updates} actualizacion(es) para revisar",
                "detail": "Son entornos de desarrollo o versiones mayores: revisalas en Aplicaciones.",
                "action_tab": TAB_APPS,
            }
        )
    if findings.junk_bytes >= junk_min_bytes:
        items.append(
            {
                "key": "junk",
                "title": f"{_fmt_size(findings.junk_bytes)} en archivos temporales",
                "detail": (
                    f"{findings.junk_files} archivos temporales seguros se pueden depurar. "
                    "Abre Almacenamiento > Temporales para revisarlos (van a Cuarentena, recuperables)."
                ),
                "action_tab": TAB_STORAGE,
            }
        )
    return items


def digest_signature(items: list[dict]) -> str:
    """Huella estable del resumen para no repetir el mismo aviso varias veces al dia."""
    text = "|".join(f"{it['key']}:{it['title']}" for it in items)
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16] if text else ""


def should_send(signature: str, last_signature: str, last_sent_ts: float, now_ts: float) -> bool:
    if not signature:
        return False
    if signature != last_signature:
        return True
    return (now_ts - float(last_sent_ts or 0.0)) >= REPEAT_AFTER_S


def collect_findings(
    progress_cb: Callable[[int, str], None] | None = None,
    controller=None,
) -> WatchFindings:
    """Revision de solo lectura (se ejecuta en segundo plano)."""
    from ..apps.app_manager import bulk_upgrade_skip_reason, check_app_updates_winget, list_installed_apps
    from ..storage.junk_scanner import scan_junk_targets
    from .task_control import stop_point

    found = WatchFindings()
    try:
        if progress_cb:
            progress_cb(10, "Vigia: consultando actualizaciones de apps...")
        apps = list_installed_apps()
        stop_point(controller)
        apps, _n, msg = check_app_updates_winget(apps)
        if msg.startswith(("winget no esta disponible", "No se pudo consultar")):
            found.errors.append(msg)
        for app in apps:
            if not app.available_version or app.protected_reason:
                continue
            if bulk_upgrade_skip_reason(app):
                found.manual_updates += 1
            else:
                found.app_updates.append(app.name)
    except Exception as exc:  # noqa: BLE001 - el vigia nunca debe romper la app
        if exc.__class__.__name__ in ("TaskCanceledError", "TaskSaveRequested"):
            raise
        found.errors.append(f"Actualizaciones: {exc}")
    stop_point(controller)
    try:
        if progress_cb:
            progress_cb(60, "Vigia: midiendo temporales seguros...")
        targets = scan_junk_targets(controller=controller)
        found.junk_bytes = int(sum(t.reclaimable_bytes for t in targets))
        found.junk_files = int(sum(t.file_count for t in targets))
    except Exception as exc:  # noqa: BLE001
        if exc.__class__.__name__ in ("TaskCanceledError", "TaskSaveRequested"):
            raise
        found.errors.append(f"Temporales: {exc}")
    if progress_cb:
        progress_cb(100, "Vigia: revision completa")
    return found
