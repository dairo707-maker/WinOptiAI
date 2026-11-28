"""v0.6.9: controladores y firmware (BIOS) pendientes, segun Windows Update. Solo lectura, sin UAC.

Usa la API oficial de Windows Update (``Microsoft.Update.Session``) para BUSCAR actualizaciones de
tipo Driver no instaladas. La instalacion la hace la persona desde Configuracion > Windows Update >
Actualizaciones opcionales (camino oficial y firmado por Microsoft/fabricante): WinOptiAI nunca
escribe firmware.
"""

from __future__ import annotations

import base64
from dataclasses import dataclass
import json
import subprocess

from ..core.win32_bridge import IS_WINDOWS

OPTIONAL_UPDATES_URI = "ms-settings:windowsupdate-optionalupdates"

_PS_SEARCH = r"""
$ErrorActionPreference = 'Stop'; $ProgressPreference = 'SilentlyContinue'
try {
  $s = New-Object -ComObject Microsoft.Update.Session
  $q = $s.CreateUpdateSearcher(); $q.Online = $true
  $r = $q.Search("IsInstalled=0 and Type='Driver' and IsHidden=0")
  $items = @()
  foreach ($u in $r.Updates) {
    $items += [PSCustomObject]@{
      title = [string]$u.Title; cls = [string]$u.DriverClass
      date = $(if ($u.DriverVerDate) { $u.DriverVerDate.ToString('yyyy-MM-dd') } else { '' })
      maker = [string]$u.DriverManufacturer; size = [int64]$u.MaxDownloadSize
    }
  }
  [Console]::Out.Write((@{ ok = $true; items = $items } | ConvertTo-Json -Depth 4 -Compress))
} catch {
  [Console]::Out.Write((@{ ok = $false; error = $_.Exception.Message } | ConvertTo-Json -Compress))
}
"""


@dataclass(slots=True)
class DriverUpdate:
    title: str
    driver_class: str = ""
    date: str = ""
    maker: str = ""
    size_bytes: int = 0

    @property
    def is_firmware(self) -> bool:
        low = f"{self.driver_class} {self.title}".lower()
        return "firmware" in low or "bios" in low

    @property
    def kind(self) -> str:
        return "BIOS / firmware" if self.is_firmware else "Controlador"


def parse_driver_search(raw: str) -> tuple[list[DriverUpdate], str]:
    """(actualizaciones, error) a partir del JSON del script de busqueda."""
    try:
        data = json.loads((raw or "").strip() or "{}")
    except json.JSONDecodeError:
        return [], "Respuesta no valida de Windows Update"
    if not isinstance(data, dict):
        return [], "Respuesta no valida de Windows Update"
    if not data.get("ok"):
        return [], str(data.get("error") or "Windows Update no respondio")
    items = data.get("items") or []
    if isinstance(items, dict):  # ConvertTo-Json con un solo elemento
        items = [items]
    out: list[DriverUpdate] = []
    for it in items:
        if not isinstance(it, dict) or not it.get("title"):
            continue
        out.append(
            DriverUpdate(
                title=str(it.get("title", "")).strip(),
                driver_class=str(it.get("cls", "") or ""),
                date=str(it.get("date", "") or ""),
                maker=str(it.get("maker", "") or ""),
                size_bytes=int(it.get("size") or 0),
            )
        )
    out.sort(key=lambda d: (not d.is_firmware, d.title.lower()))
    return out, ""


def check_pending_driver_updates(timeout: float = 120.0) -> tuple[list[DriverUpdate], str]:
    """Busca controladores/firmware pendientes en Windows Update (sin UAC, ~15 s)."""
    if not IS_WINDOWS:
        return [], "Solo Windows"
    encoded = base64.b64encode(_PS_SEARCH.encode("utf-16-le")).decode("ascii")
    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand", encoded],
            capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except subprocess.TimeoutExpired:
        return [], "Windows Update tardo demasiado en responder (revisa tu conexion)"
    except OSError as exc:
        return [], f"No se pudo consultar Windows Update: {exc}"
    return parse_driver_search(res.stdout)


def summarize_driver_updates(updates: list[DriverUpdate], error: str = "") -> str:
    """Resumen claro para la persona."""
    if error:
        return f"No se pudo revisar Windows Update: {error}."
    if not updates:
        return "Todo al dia: Windows Update no tiene controladores ni BIOS/firmware pendientes para este equipo."
    fw = [u for u in updates if u.is_firmware]
    parts = []
    if fw:
        parts.append(f"{len(fw)} de BIOS/firmware")
    if len(updates) - len(fw):
        parts.append(f"{len(updates) - len(fw)} de controladores")
    return (
        f"Hay {len(updates)} actualizacion(es) disponibles en Windows Update ({' y '.join(parts)}). "
        "Instalalas desde Windows Update > Actualizaciones opcionales."
    )
