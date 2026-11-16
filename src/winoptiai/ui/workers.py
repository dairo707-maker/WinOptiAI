"""Concurrent RAM-aware QThreadPool task runner with per-task progress (%) and ETA."""

from __future__ import annotations

from datetime import datetime
import inspect
import time
from typing import Any, Callable
import uuid

from PySide6.QtCore import QObject, QRunnable, Signal


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
    progress = Signal(str, int, str)  # task_id, percent (0..100), stage_text
    finished = Signal(str, object)    # task_id, result
    error = Signal(str, str)          # task_id, error_msg


class AsyncTask(QRunnable):
    """Run any blocking storage, WMI, or Win32 call off the Qt main thread with % + ETA."""

    def __init__(self, title: str, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.task_id = uuid.uuid4().hex[:8]
        self.title = title
        self.started_at = datetime.now().astimezone().strftime("%H:%M:%S")
        self.started_monotonic = time.monotonic()
        self.percent = 0
        self.stage = "Iniciando..."
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def eta_label(self) -> str:
        """Return realistic remaining time estimate once task progresses past initialization."""
        if self.percent <= 6 or self.percent >= 100:
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
            self._emit_progress(5, "Procesando en segundo plano...")
            result = self.fn(*self.args, **call_kwargs)
            self._emit_progress(100, "Completado")
            try:
                self.signals.finished.emit(self.task_id, result)
            except RuntimeError:
                pass
        except Exception as exc:  # noqa: BLE001
            try:
                self.signals.error.emit(self.task_id, str(exc))
            except RuntimeError:
                pass
