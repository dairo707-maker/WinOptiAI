"""Informe de error anonimizado para GitHub Issues (v0.5.3).

Nada se envia automaticamente: la app arma el texto, lo muestra al usuario y, si este
acepta, abre ``github.com/<repo>/issues/new`` en el navegador con el informe precargado.
El usuario revisa y pulsa "Submit" en GitHub. No hay tokens ni claves dentro del .exe.
"""

from __future__ import annotations

from datetime import datetime
import os
from pathlib import Path
import platform
import re
import sys
from urllib.parse import quote

from .crash_guard import CrashGuard
from .safety_guard import default_app_data_dir

GITHUB_REPO = "dairo707-maker/WinOptiAI"
ISSUE_BASE_URL = f"https://github.com/{GITHUB_REPO}/issues/new"
# v0.5.7: si el usuario no inicio sesion, GitHub redirige a /login?return_to=<URL codificada otra
# vez> y la direccion casi se duplica; con ~5.900 caracteres GitHub responde "Whoops, something
# went wrong!" (HTTP 500, verificado el 17/11/2026). Con 3.000 queda margen en ambos casos: la URL
# lleva el resumen y el informe completo va en el portapapeles y en un archivo local.
MAX_ISSUE_URL_CHARS = 3000

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
    # v0.5.7: crash.log trae saltos CRLF; normalizar ahorra espacio en la URL de GitHub.
    return anonymize_text("\n".join(lines)).replace("\r\n", "\n").replace("\r", "\n")


def build_issue_title(guard: CrashGuard, kind: str = KIND_CRASH, error_type: str = "") -> str:
    if kind == KIND_ERROR:
        return f"[Error] v{guard.version}: {error_type or 'excepcion no controlada'}"
    return f"[Cierre inesperado] v{guard.version}"


def build_issue_url(title: str, body: str, max_chars: int = MAX_ISSUE_URL_CHARS) -> tuple[str, bool]:
    """URL de GitHub con el informe precargado. Devuelve (url, recortado)."""
    note = (
        "\n\n**Informe recortado por longitud.** El texto completo ya esta en su portapapeles: "
        "borre esta linea y pegue con Ctrl+V. Tambien quedo guardado en "
        "`%LOCALAPPDATA%\\WinOptiAI\\reports`."
    )
    prefix = f"{ISSUE_BASE_URL}?labels=crash&title={quote(title)}&body="
    url = prefix + quote(body)
    if len(url) <= max_chars:
        return url, False
    budget = max_chars - len(prefix) - len(quote(note + "\n```"))
    # Recortar por lineas completas conservando el inicio (resumen, eventos, error).
    kept: list[str] = []
    used = 0
    for line in body.splitlines(keepends=True):
        cost = len(quote(line))
        if used + cost > budget:
            break
        kept.append(line)
        used += cost
    head = "".join(kept).rstrip("\n")
    if head.count("```") % 2 == 1:  # no dejar un bloque de codigo abierto
        head += "\n```"
    return prefix + quote(head + note), True


# v0.6.9 (decision del propietario 28/11/2026): los informes se envian por CORREO, sin cuenta de
# GitHub. La app abre el programa de correo del usuario con el informe anonimizado ya escrito.
REPORT_EMAIL = "datg.2007@hotmail.com"
# Windows recorta los enlaces mailto largos (~2.000 caracteres): el resto va al portapapeles/archivo.
MAX_MAILTO_CHARS = 1900


def build_mailto_url(
    subject: str, body: str, max_chars: int = MAX_MAILTO_CHARS, to: str = REPORT_EMAIL
) -> tuple[str, bool]:
    """Enlace ``mailto:`` con el informe precargado. Devuelve (url, recortado)."""
    note = (
        "\n\n[Informe recortado por longitud. El texto completo esta en su portapapeles: "
        "pegue con Ctrl+V debajo de esta linea, o adjunte el archivo de "
        "%LOCALAPPDATA%\\WinOptiAI\\reports.]"
    )
    prefix = f"mailto:{to}?subject={quote(subject)}&body="
    url = prefix + quote(body)
    if len(url) <= max_chars:
        return url, False
    budget = max_chars - len(prefix) - len(quote(note))
    kept: list[str] = []
    used = 0
    for line in body.splitlines(keepends=True):
        cost = len(quote(line))
        if used + cost > budget:
            break
        kept.append(line)
        used += cost
    return prefix + quote("".join(kept).rstrip("\n") + note), True


def save_report_file(text: str, app_dir: Path | None = None) -> Path | None:
    """Guardar el informe completo en %LOCALAPPDATA%\\WinOptiAI\\reports (respaldo del portapapeles)."""
    base = (app_dir or default_app_data_dir()) / "reports"
    try:
        base.mkdir(parents=True, exist_ok=True)
        path = base / f"informe_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
        path.write_text(text, encoding="utf-8")
        return path
    except OSError:
        return None
