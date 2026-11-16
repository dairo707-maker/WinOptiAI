"""Concurrent RAM-aware QThreadPool task runner with Pause, Save Session, Cancel, and ETA."""

from __future__ import annotations

from datetime import datetime
import inspect
import time
from typing import Any, Callable
import uuid

from PySide6.QtCore import QObject, QRunnable, Signal

from ..core.task_control import TaskCanceledError, TaskController, TaskPausedAndSaved


def format_eta_seconds(seconds: float) -> str:
    """Format an estimated remaining duration in compact Spanish units."""
    sec = max(1, int(round(seconds)))
    if sec < 60:
        return f"~{sec}s rest."
    mins, rem_s = divmod(sec, 60)
    if mins < 60:
        return f"~{mins}m {rem_s:02d}s rest."
    hours, rem_m = divmod(mins, 60)
    return f"~{hours}h {rem_m:02d}m rest."


class WorkerSignals(QObject):
    progress = Signal(str, int, str)        # task_id, percent (0..100), stage_text
    finished = Signal(str, object)          # task_id, result
    paused_saved = Signal(str, str, int, str)  # task_id, session_id, percent, detail
    canceled = Signal(str, str)             # task_id, detail
    error = Signal(str, str)                # task_id, error_msg


class AsyncTask(QRunnable):
    """Run any blocking storage, WMI, or Win32 call off the Qt main thread with % + ETA + control."""

    def __init__(self, title: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.task_id = uuid.uuid4().hex[:8]
        self.title = title
        self.started_at = datetime.now().astimezone().strftime("%H:%M:%S")
        self.started_monotonic = time.monotonic()
        self.percent = 0
        self.stage = "Iniciando..."
        self._last_emit_pct = -1
        self._last_emit_ts = 0.0
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.controller = TaskController(self.task_id)
        self.signals = WorkerSignals()

    def eta_label(self) -> str:
        """Return realistic remaining time estimate once task progresses past initialization."""
        if self.controller.is_paused:
            return "PAUSADO"
        if self.percent <= 5 or self.percent >= 100:
            return ""
        elapsed = time.monotonic() - self.started_monotonic
        if elapsed < 1.2:
            return ""
        remaining = elapsed * (100 - self.percent) / self.percent
        return format_eta_seconds(remaining)

    def _emit_progress(self, pct: int, stage: str) -> None:
        clamped = max(0, min(100, int(pct)))
        self.percent = clamped
        self.stage = stage
        # v0.5.2: limitar senales cruzadas de hilo. Procesos con cientos de miles de archivos
        # informaban por archivo y encolaban miles de eventos en el hilo GUI (cada uno
        # redibuja indicadores y el panel de tareas). Maximo ~10 senales/s por tarea; el % real
        # sigue disponible en self.percent para el temporizador de ETA de 1 s.
        now = time.monotonic()
        if self._last_emit_pct < 0 or clamped >= 100 or (now - self._last_emit_ts) >= 0.10:
            self._last_emit_pct = clamped
            self._last_emit_ts = now
        else:
            return
        try:
            self.signals.progress.emit(self.task_id, clamped, stage)
        except RuntimeError:
            pass

    def run(self) -> None:
        try:
            call_kwargs = dict(self.kwargs)
            sig = inspect.signature(self.fn)
            if "progress_cb" in sig.parameters and "progress_cb" not in call_kwargs:
                call_kwargs["progress_cb"] = self._emit_progress
            if "controller" in sig.parameters and "controller" not in call_kwargs:
                call_kwargs["controller"] = self.controller
            self._emit_progress(5, "Procesando en segundo plano...")
            result = self.fn(*self.args, **call_kwargs)
            self._emit_progress(100, "Completado")
            try:
                self.signals.finished.emit(self.task_id, result)
            except RuntimeError:
                pass
        except TaskPausedAndSaved as paused_exc:
            try:
                self.signals.paused_saved.emit(
                    self.task_id, paused_exc.session_id, paused_exc.percent, paused_exc.detail
                )
            except RuntimeError:
                pass
        except TaskCanceledError as cancel_exc:
            try:
                self.signals.canceled.emit(self.task_id, cancel_exc.detail)
            except RuntimeError:
                pass
        except Exception as exc:  # noqa: BLE001
            try:
                self.signals.error.emit(self.task_id, str(exc))
            except RuntimeError:
                pass
