"""Instancia unica de WinOptiAI (v0.5.7).

Causa de los eventos duplicados en ``audit.jsonl`` (16/11 22:45:35): habia DOS procesos de la
app abiertos a la vez (PID 4144 y 22604 en ``crash.log``). Cada uno tenia su propio motor SRE,
ambos detectaron presion de RAM en el mismo ciclo y ambos ejecutaron y registraron AI Boost.

Solucion: mutex con nombre de Windows (el kernel lo libera si el proceso muere, sin bloqueos
huerfanos). La segunda instancia avisa a la primera por una tuberia local (``QLocalSocket``)
para que muestre su ventana, y termina. El relanzamiento como Administrador espera a que la
instancia anterior cierre antes de rendirse.
"""

from __future__ import annotations

import ctypes
import getpass
import hashlib

from .win32_bridge import IS_WINDOWS

ERROR_ALREADY_EXISTS = 183
WAIT_OBJECT_0 = 0x00000000
WAIT_ABANDONED = 0x00000080


def instance_key(app_name: str = "WinOptiAI") -> str:
    """Nombre estable por usuario (sin datos personales legibles)."""
    try:
        user = getpass.getuser()
    except Exception:  # noqa: BLE001
        user = "user"
    digest = hashlib.sha1(f"{app_name}|{user}".encode("utf-8")).hexdigest()[:12]
    return f"{app_name}-{digest}"


class SingleInstanceLock:
    """Mutex ``Local\\<clave>`` propiedad del hilo principal mientras viva el proceso."""

    def __init__(self, key: str | None = None) -> None:
        self.key = key or instance_key()
        self._handle = None
        self.acquired = False

    def acquire(self, wait_ms: int = 0) -> bool:
        if not IS_WINDOWS:
            self.acquired = True
            return True
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateMutexW.restype = ctypes.c_void_p
        k32.CreateMutexW.argtypes = [ctypes.c_void_p, ctypes.c_int, ctypes.c_wchar_p]
        k32.WaitForSingleObject.restype = ctypes.c_uint32
        k32.WaitForSingleObject.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
        handle = k32.CreateMutexW(None, 0, f"Local\\{self.key}")
        if not handle:
            # Sin mutex no bloqueamos el arranque (mejor dos instancias que ninguna).
            self.acquired = True
            return True
        self._handle = handle
        rc = k32.WaitForSingleObject(handle, max(0, int(wait_ms)))
        self.acquired = rc in (WAIT_OBJECT_0, WAIT_ABANDONED)
        return self.acquired

    def release(self) -> None:
        if not IS_WINDOWS or not self._handle:
            return
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.ReleaseMutex.argtypes = [ctypes.c_void_p]
        k32.CloseHandle.argtypes = [ctypes.c_void_p]
        if self.acquired:
            k32.ReleaseMutex(self._handle)
        k32.CloseHandle(self._handle)
        self._handle = None
        self.acquired = False
