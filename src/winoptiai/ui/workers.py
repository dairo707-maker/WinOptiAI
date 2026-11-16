"""Lightweight QThreadPool task runner for fluid UI responsiveness."""

from __future__ import annotations

from typing import Any, Callable

from PySide6.QtCore import QObject, QRunnable, Signal


class WorkerSignals(QObject):
    finished = Signal(object)
    error = Signal(str)


class AsyncTask(QRunnable):
    """Run any blocking storage, WMI, or Win32 call off the Qt main thread."""

    def __init__(self, fn: Callable[..., Any], *args: Any, **kwargs: Any) -> None:
        super().__init__()
        self.fn = fn
        self.args = args
        self.kwargs = kwargs
        self.signals = WorkerSignals()

    def run(self) -> None:
        try:
            result = self.fn(*self.args, **self.kwargs)
            try:
                self.signals.finished.emit(result)
            except RuntimeError:
                pass
        except Exception as exc:  # noqa: BLE001
            try:
                self.signals.error.emit(str(exc))
            except RuntimeError:
                pass
