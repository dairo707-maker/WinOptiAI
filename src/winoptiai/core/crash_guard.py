"""Detector de cierres inesperados y telemetria post-mortem local (v0.5.1).

- ``faulthandler`` escribe en ``%LOCALAPPDATA%\\WinOptiAI\\crash.log`` incluso ante fallos
  nativos (``0xc0000005`` en Qt/Shiboken), con la pila de todos los hilos.
- ``sys.excepthook`` / ``threading.excepthook`` / ``qInstallMessageHandler`` registran
  fecha, version, traceback completo y los ultimos eventos (breadcrumbs).
- ``session_lock.json`` marca la sesion en curso; si al arrancar no indica ``clean_exit``,
  la sesion previa termino abruptamente (``dirty exit``).

- v0.5.3: vigilante de bloqueos del hilo GUI (vuelca pilas si no responde > 8 s).

Todo es local: nada se envia automaticamente. El usuario decide si abre un informe
anonimizado en GitHub (``crash_reporter``).
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from datetime import datetime
import faulthandler
import json
import os
from pathlib import Path
import subprocess
import sys
import threading
import time
import traceback
from types import TracebackType
from typing import Any, TextIO

from .safety_guard import atomic_write_text, default_app_data_dir
from .win32_bridge import IS_WINDOWS

CRASH_LOG_NAME = "crash.log"
SESSION_LOCK_NAME = "session_lock.json"
MAX_CRASH_LOG_BYTES = 1_000_000
MAX_BREADCRUMBS = 40
HANG_THRESHOLD_S = 8.0


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


@dataclass
class PreviousSessionReport:
    """Resultado de comparar el marcador de la sesion anterior al arrancar."""

    dirty: bool
    pid: int = 0
    version: str = ""
    started_at: str = ""
    last_heartbeat: str = ""
    crash_log_tail: str = ""
    event_log_entries: list[str] = field(default_factory=list)

    def summary(self) -> str:
        if not self.dirty:
            return "La sesion anterior cerro correctamente."
        return (
            f"La sesion anterior (v{self.version or '?'}, PID {self.pid or '?'}, "
            f"iniciada {self.started_at or 'desconocido'}) no cerro de forma controlada."
        )


def _pid_is_other_live_instance(pid: int) -> bool:
    """True si el PID del marcador sigue vivo y parece otra instancia de WinOptiAI."""
    if pid <= 0 or pid == os.getpid():
        return False
    try:
        import psutil

        proc = psutil.Process(pid)
        name = proc.name().lower()
        return "winoptiai" in name or name.startswith("python")
    except Exception:  # noqa: BLE001
        return False


class CrashGuard:
    """Gestiona crash.log, hooks de excepciones y el marcador de sesion limpia."""

    def __init__(self, app_dir: Path | None = None, version: str = "") -> None:
        self.app_dir = app_dir or default_app_data_dir()
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.crash_log_path = self.app_dir / CRASH_LOG_NAME
        self.session_lock_path = self.app_dir / SESSION_LOCK_NAME
        if not version:
            try:
                from .. import __version__ as version  # type: ignore[no-redef]
            except Exception:  # noqa: BLE001
                version = "0.0.0"
        self.version = version
        self.previous_session: PreviousSessionReport | None = None
        self._breadcrumbs: deque[str] = deque(maxlen=MAX_BREADCRUMBS)
        self._fh_stream: TextIO | None = None
        self._write_lock = threading.Lock()
        self._installed = False
        self._prev_sys_hook: Any = None
        self._prev_thread_hook: Any = None
        self._session_started_at = ""
        self._last_ui_tick = time.monotonic()
        self._watchdog_stop = threading.Event()
        self._watchdog_thread: threading.Thread | None = None
        self.hang_count = 0
        self._unhandled_listeners: list[Any] = []

    def add_unhandled_listener(self, fn: Any) -> None:
        """Registrar callback(origin, exc_type, text) para excepciones no controladas."""
        self._unhandled_listeners.append(fn)

    def _notify_unhandled(self, origin: str, exc_type: Any, text: str) -> None:
        for fn in list(self._unhandled_listeners):
            try:
                fn(origin, getattr(exc_type, "__name__", str(exc_type)), text)
            except Exception:  # noqa: BLE001
                pass

    # ------------------------------------------------------------------ breadcrumbs
    def breadcrumb(self, message: str) -> None:
        """Registrar un evento reciente (se adjunta al crash.log si ocurre un fallo)."""
        self._breadcrumbs.append(f"{_now_iso()} {message}")

    def recent_breadcrumbs(self) -> list[str]:
        return list(self._breadcrumbs)

    # ------------------------------------------------------------------ crash.log
    def _rotate_if_needed(self) -> None:
        try:
            if self.crash_log_path.exists() and self.crash_log_path.stat().st_size > MAX_CRASH_LOG_BYTES:
                old = self.crash_log_path.with_suffix(".log.1")
                if old.exists():
                    old.unlink()
                self.crash_log_path.replace(old)
        except OSError:
            pass

    def write_log_block(self, title: str, body: str) -> None:
        """Anexar un bloque legible al crash.log (thread-safe)."""
        crumbs = "\n".join(f"  - {c}" for c in self._breadcrumbs) or "  (sin eventos)"
        block = (
            f"\n===== {title} | {_now_iso()} | WinOptiAI v{self.version} | PID {os.getpid()} "
            f"| hilo {threading.current_thread().name} =====\n"
            f"{body.rstrip()}\n"
            f"--- Ultimos eventos ---\n{crumbs}\n"
        )
        with self._write_lock:
            try:
                if self._fh_stream is not None and not self._fh_stream.closed:
                    self._fh_stream.write(block)
                    self._fh_stream.flush()
                else:
                    with self.crash_log_path.open("a", encoding="utf-8") as fh:
                        fh.write(block)
            except OSError:
                pass

    def log_exception(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
        origin: str = "sys.excepthook",
    ) -> None:
        text = "".join(traceback.format_exception(exc_type, exc, tb)) if exc_type else "Excepcion sin tipo"
        self.write_log_block(f"EXCEPCION NO CONTROLADA ({origin})", text)
        if exc_type is not None and issubclass(exc_type, (KeyboardInterrupt, SystemExit)):
            return
        self._notify_unhandled(origin, exc_type, text)

    def read_crash_log_tail(self, max_chars: int = 6000) -> str:
        try:
            if not self.crash_log_path.exists():
                return ""
            with self.crash_log_path.open("rb") as fh:
                fh.seek(0, os.SEEK_END)
                size = fh.tell()
                fh.seek(max(0, size - max_chars * 2))
                data = fh.read().decode("utf-8", errors="replace")
            return data[-max_chars:]
        except OSError:
            return ""

    # ------------------------------------------------------------------ hooks
    def install(self) -> None:
        """Activar faulthandler + hooks de excepciones de Python e hilos."""
        if self._installed:
            return
        self._rotate_if_needed()
        try:
            self._fh_stream = self.crash_log_path.open("a", encoding="utf-8")
            faulthandler.enable(file=self._fh_stream, all_threads=True)
        except (OSError, RuntimeError, ValueError):
            self._fh_stream = None

        self._prev_sys_hook = sys.excepthook
        self._prev_thread_hook = threading.excepthook

        def _sys_hook(exc_type, exc, tb) -> None:  # type: ignore[no-untyped-def]
            self.log_exception(exc_type, exc, tb, "sys.excepthook")
            if self._prev_sys_hook is not None and self._prev_sys_hook is not sys.__excepthook__:
                try:
                    self._prev_sys_hook(exc_type, exc, tb)
                except Exception:  # noqa: BLE001
                    pass
            else:
                sys.__excepthook__(exc_type, exc, tb)

        def _thread_hook(args: threading.ExceptHookArgs) -> None:
            name = args.thread.name if args.thread is not None else "?"
            self.log_exception(args.exc_type, args.exc_value, args.exc_traceback, f"threading:{name}")
            if self._prev_thread_hook is not None:
                try:
                    self._prev_thread_hook(args)
                except Exception:  # noqa: BLE001
                    pass

        sys.excepthook = _sys_hook
        threading.excepthook = _thread_hook
        self._installed = True

    def install_qt_message_handler(self) -> None:
        """Capturar mensajes Qt criticos/fatales (requiere PySide6 importado)."""
        try:
            from PySide6.QtCore import QtMsgType, qInstallMessageHandler
        except ImportError:
            return

        def _handler(mode, context, message) -> None:  # type: ignore[no-untyped-def]
            if mode in (QtMsgType.QtCriticalMsg, QtMsgType.QtFatalMsg):
                where = ""
                try:
                    if context is not None and context.file:
                        where = f" ({context.file}:{context.line} {context.function})"
                except Exception:  # noqa: BLE001
                    where = ""
                level = "FATAL" if mode == QtMsgType.QtFatalMsg else "CRITICO"
                self.write_log_block(f"MENSAJE QT {level}", f"{message}{where}")
            elif mode == QtMsgType.QtWarningMsg:
                self.breadcrumb(f"Qt warning: {str(message)[:160]}")

        qInstallMessageHandler(_handler)

    def uninstall(self) -> None:
        """Restaurar hooks originales (uso en pruebas)."""
        self.stop_hang_watchdog()
        if not self._installed:
            return
        if self._prev_sys_hook is not None:
            sys.excepthook = self._prev_sys_hook
        if self._prev_thread_hook is not None:
            threading.excepthook = self._prev_thread_hook
        try:
            faulthandler.disable()
        except Exception:  # noqa: BLE001
            pass
        with self._write_lock:
            if self._fh_stream is not None:
                try:
                    self._fh_stream.close()
                except OSError:
                    pass
                self._fh_stream = None
        self._installed = False

    # ------------------------------------------------------------------ session lock
    def _read_lock(self) -> dict[str, Any] | None:
        try:
            if not self.session_lock_path.exists():
                return None
            data = json.loads(self.session_lock_path.read_text(encoding="utf-8"))
            return data if isinstance(data, dict) else None
        except (OSError, ValueError):
            # Marcador corrupto: tratarlo como cierre abrupto (no se pudo escribir limpio).
            return {"pid": 0, "version": "", "started_at": "", "clean_exit": False}

    def _write_lock_state(self, clean_exit: bool) -> None:
        payload = {
            "pid": os.getpid(),
            "version": self.version,
            "started_at": self._session_started_at or _now_iso(),
            "last_heartbeat": _now_iso(),
            "clean_exit": clean_exit,
        }
        try:
            atomic_write_text(self.session_lock_path, json.dumps(payload, indent=2))
        except OSError:
            pass

    def begin_session(self) -> PreviousSessionReport:
        """Evaluar el marcador anterior y crear el de la sesion actual."""
        prev = self._read_lock()
        report = PreviousSessionReport(dirty=False)
        if prev is not None and not bool(prev.get("clean_exit", False)):
            pid = int(prev.get("pid", 0) or 0)
            if not _pid_is_other_live_instance(pid):
                report = PreviousSessionReport(
                    dirty=True,
                    pid=pid,
                    version=str(prev.get("version", "")),
                    started_at=str(prev.get("started_at", "")),
                    last_heartbeat=str(prev.get("last_heartbeat", "")),
                    crash_log_tail=self.read_crash_log_tail(),
                )
        self.previous_session = report
        self._session_started_at = _now_iso()
        self._write_lock_state(clean_exit=False)
        self.breadcrumb(f"Sesion iniciada (v{self.version})")
        if report.dirty:
            self.write_log_block("CIERRE INESPERADO DETECTADO EN SESION PREVIA", report.summary())
        return report

    def heartbeat(self) -> None:
        """Actualizar marca de vida (ayuda a fechar el momento aproximado de un crash)."""
        self._write_lock_state(clean_exit=False)

    def mark_clean_exit(self) -> None:
        """Marcar cierre controlado (closeEvent / tray / aboutToQuit). Idempotente."""
        self.breadcrumb("Cierre controlado")
        self._write_lock_state(clean_exit=True)

    # ------------------------------------------------------------------ hang watchdog
    def ui_tick(self) -> None:
        """Llamado por un QTimer del hilo GUI (~1 s): prueba de que la interfaz responde."""
        self._last_ui_tick = time.monotonic()

    def start_hang_watchdog(self, threshold_s: float = HANG_THRESHOLD_S, poll_s: float = 1.0) -> None:
        """v0.5.3: si el hilo GUI no responde durante ``threshold_s``, volcar las pilas de todos los
        hilos en crash.log. faulthandler solo cubre fallos nativos; un bloqueo ("No responde")
        que Windows termina no dejaba rastro de que estaba haciendo la app."""
        if self._watchdog_thread is not None:
            return
        self._last_ui_tick = time.monotonic()
        self._watchdog_stop.clear()

        def _loop() -> None:
            dumped_since: float | None = None
            last_loop = time.monotonic()
            while not self._watchdog_stop.wait(poll_s):
                now = time.monotonic()
                # v0.5.9: si el propio vigilante estuvo detenido mucho mas que su intervalo, el equipo
                # estuvo suspendido (el reloj sigue contando el tiempo dormido): no es un bloqueo.
                if now - last_loop > max(threshold_s, poll_s * 5):
                    self._last_ui_tick = now
                    self.breadcrumb(f"Reanudacion tras suspension ({now - last_loop:.0f} s)")
                    dumped_since = None
                last_loop = now
                gap = now - self._last_ui_tick
                if gap >= threshold_s and dumped_since is None:
                    dumped_since = self._last_ui_tick
                    self.hang_count += 1
                    self.dump_all_threads(f"BLOQUEO DE INTERFAZ (sin responder {gap:.0f} s)")
                elif gap < threshold_s and dumped_since is not None:
                    self.breadcrumb(f"Interfaz recuperada tras {time.monotonic() - dumped_since:.0f} s")
                    dumped_since = None

        self._watchdog_thread = threading.Thread(target=_loop, name="WinOptiAI-HangWatchdog", daemon=True)
        self._watchdog_thread.start()

    def stop_hang_watchdog(self) -> None:
        self._watchdog_stop.set()
        self._watchdog_thread = None

    def dump_all_threads(self, title: str) -> None:
        self.write_log_block(title, "Pilas de todos los hilos (el hilo GUI es MainThread):")
        with self._write_lock:
            try:
                if self._fh_stream is not None and not self._fh_stream.closed:
                    faulthandler.dump_traceback(file=self._fh_stream, all_threads=True)
                    self._fh_stream.flush()
                else:
                    with self.crash_log_path.open("a", encoding="utf-8") as fh:
                        faulthandler.dump_traceback(file=fh, all_threads=True)
            except (OSError, ValueError, RuntimeError):
                pass

    # ------------------------------------------------------------------ Event Log
    def query_recent_appcrash_events(self, max_events: int = 3, exe_name: str = "WinOptiAI.exe") -> list[str]:
        """Leer los ultimos eventos APPCRASH (ID 1000) del registro Application (solo lectura)."""
        if not IS_WINDOWS:
            return []
        # v0.5.3: incluir bloqueos ("dejo de interactuar con Windows", Application Hang 1002).
        query = (
            "*[System[(Provider[@Name='Application Error'] and EventID=1000) or "
            "(Provider[@Name='Application Hang'] and EventID=1002)]]"
        )
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            res = subprocess.run(
                ["wevtutil", "qe", "Application", f"/q:{query}", "/c:25", "/rd:true", "/f:text"],
                capture_output=True,
                text=True,
                encoding="mbcs",  # v0.5.3: wevtutil escribe en ANSI; "oem" danaba los acentos
                errors="replace",
                timeout=12,
                creationflags=flags,
            )
        except (OSError, subprocess.SubprocessError):
            return []
        if res.returncode != 0 or not res.stdout:
            return []
        out: list[str] = []
        needle = exe_name.lower()
        for chunk in res.stdout.split("Event["):
            if needle not in chunk.lower():
                continue
            lines = [ln.strip() for ln in chunk.splitlines() if ln.strip()]
            date = next((ln for ln in lines if ln.lower().startswith("date:")), "")
            desc_idx = next((i for i, ln in enumerate(lines) if ln.lower().startswith("description:")), -1)
            desc = " ".join(lines[desc_idx + 1 : desc_idx + 4]) if desc_idx >= 0 else ""
            out.append(f"{date} | {desc}".replace("\x00", "").strip()[:400])
            if len(out) >= max_events:
                break
        return out

    # ------------------------------------------------------------------ diagnostic
    def build_diagnostic_text(self) -> str:
        """Texto plano para copiar al portapapeles o adjuntar en un reporte."""
        prev = self.previous_session
        parts = [
            f"WinOptiAI v{self.version} - Diagnostico post-mortem",
            f"Generado: {_now_iso()}",
            f"Python: {sys.version.split()[0]} | Plataforma: {sys.platform}",
            f"crash.log: {self.crash_log_path}",
            "",
            prev.summary() if prev else "Sin evaluacion de sesion previa.",
        ]
        if prev and prev.event_log_entries:
            parts.append("")
            parts.append("Eventos APPCRASH (Visor de eventos / Application):")
            parts.extend(f"  {e}" for e in prev.event_log_entries)
        tail = self.read_crash_log_tail(4000)
        parts.append("")
        parts.append("--- Final de crash.log ---")
        parts.append(tail or "(crash.log vacio)")
        return "\n".join(parts)
