"""Informe de error anonimizado para GitHub Issues (v0.5.3).

Nada se envia automaticamente: la app arma el texto, lo muestra al usuario y, si este
acepta, abre ``github.com/<repo>/issues/new`` en el navegador con el informe precargado.
El usuario revisa y pulsa "Submit" en GitHub. No hay tokens ni claves dentro del .exe.
"""

from __future__ import annotations

import os
import platform
import re
import sys
from urllib.parse import quote

from .crash_guard import CrashGuard

GITHUB_REPO = "dairo707-maker/WinOptiAI"
ISSUE_BASE_URL = f"https://github.com/{GITHUB_REPO}/issues/new"
# GitHub rechaza URLs muy largas (~8 KB). Margen para titulo y etiquetas.
MAX_ISSUE_URL_CHARS = 7600

KIND_CRASH = "crash"  # cierre inesperado (fallo nativo o terminado por Windows)
KIND_ERROR = "error"  # excepcion de Python no controlada (la app sigue abierta)

_USERS_RE = re.compile(r"(?i)([A-Z]:[\\/]+Users[\\/]+)([^\\/\s:\"'|]+)")
_ONEDRIVE_ORG_RE = re.compile(r"(OneDrive - )([^\\/\n\r|\"']+)")
_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+")


def anonymize_text(text: str) -> str:
    """Quitar datos personales: usuario de Windows, nombre del equipo, organizacion OneDrive, correos."""
    if not text:
        return ""
    out = _EMAIL_RE.sub("<correo>", text)
    out = _USERS_RE.sub(r"\1<usuario>", out)
    out = _ONEDRIVE_ORG_RE.sub(r"\1<organizacion>", out)
    for var, placeholder in (("USERNAME", "<usuario>"), ("COMPUTERNAME", "<equipo>"), ("USERDOMAIN", "<dominio>")):
        value = (os.environ.get(var) or "").strip()
        if len(value) >= 3:
            out = re.sub(rf"(?i)(?<![\w]){re.escape(value)}(?![\w])", placeholder, out)
    return out


def _windows_label() -> str:
    try:
        version = platform.version()
        release = platform.release()
        try:
            if int(version.split(".")[-1]) >= 22000:  # Windows 11 sigue reportando "10"
                release = "11"
        except ValueError:
            pass
        return f"Windows {release} (build {version}) {platform.machine()}"
    except Exception:  # noqa: BLE001
        return sys.platform


def build_report_markdown(
    guard: CrashGuard,
    kind: str = KIND_CRASH,
    error_text: str = "",
    auto_restarted: bool = False,
    log_chars: int = 3500,
) -> str:
    """Informe Markdown anonimizado (lo que el usuario ve y lo que llega a GitHub)."""
    prev = guard.previous_session
    lines = [
        "### Resumen",
        f"- Tipo: {'Cierre inesperado' if kind == KIND_CRASH else 'Error no controlado (la app siguio abierta)'}",
        f"- WinOptiAI: v{guard.version} ({'instalado/portable' if getattr(sys, 'frozen', False) else 'desarrollo'})",
        f"- Sistema: {_windows_label()}",
        f"- Python: {sys.version.split()[0]}",
    ]
    if kind == KIND_CRASH and prev is not None and prev.dirty:
        lines.append(f"- Sesion afectada: v{prev.version or '?'}, iniciada {prev.started_at or '?'}")
        lines.append(f"- Ultima senal de vida: {prev.last_heartbeat or '?'}")
        if auto_restarted:
            lines.append("- Windows reinicio la app automaticamente tras el cierre.")
    if kind == KIND_CRASH and prev is not None and prev.event_log_entries:
        lines += ["", "### Visor de eventos (Application)"]
        lines += [f"- {e}" for e in prev.event_log_entries]
    if error_text:
        lines += ["", "### Error", "```", error_text.strip()[-2500:], "```"]
    tail = guard.read_crash_log_tail(log_chars) if log_chars > 0 else ""
    if tail:
        lines += ["", "### Final de crash.log", "```", tail.strip(), "```"]
    lines += ["", "### Que estaba haciendo", "(Describa brevemente que hacia en la app cuando ocurrio.)"]
    return anonymize_text("\n".join(lines))


def build_issue_title(guard: CrashGuard, kind: str = KIND_CRASH, error_type: str = "") -> str:
    if kind == KIND_ERROR:
        return f"[Error] v{guard.version}: {error_type or 'excepcion no controlada'}"
    return f"[Cierre inesperado] v{guard.version}"


def build_issue_url(title: str, body: str, max_chars: int = MAX_ISSUE_URL_CHARS) -> tuple[str, bool]:
    """URL de GitHub con el informe precargado. Devuelve (url, recortado)."""
    note = "\n\n_(Informe recortado por longitud: pegue aqui el texto completo, ya esta en su portapapeles.)_"
    prefix = f"{ISSUE_BASE_URL}?labels=crash&title={quote(title)}&body="
    url = prefix + quote(body)
    if len(url) <= max_chars:
        return url, False
    budget = max_chars - len(prefix) - len(quote(note))
    # Recortar el final conservando el inicio (resumen, eventos, error) del informe.
    lo, hi = 0, len(body)
    while lo < hi:
        mid = (lo + hi + 1) // 2
        if len(quote(body[:mid])) <= budget:
            lo = mid
        else:
            hi = mid - 1
    return prefix + quote(body[:lo] + note), True
