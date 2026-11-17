"""Cooperative TaskController (Pause / Cancel / Resume) and persistent SessionManager."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from pathlib import Path
import threading
import time
from typing import Any
import uuid

from .safety_guard import atomic_write_text, default_app_data_dir


class TaskPausedAndSaved(Exception):
    """Raised cleanly when a user pauses and persists a long task for later resumption."""

    def __init__(self, session_id: str, percent: int, detail: str = "") -> None:
        super().__init__(detail or f"Sesion pausada y guardada ({percent}%)")
        self.session_id = session_id
        self.percent = percent
        self.detail = detail


class TaskCanceledError(Exception):
    """Raised cleanly when a user cancels an active background task."""

    def __init__(self, detail: str = "Operacion cancelada por el usuario") -> None:
        super().__init__(detail)
        self.detail = detail


class TaskSaveRequested(Exception):
    """v0.5.9: el usuario pidio "Guardar Pausa" en un analisis. El trabajador (AsyncTask) crea la
    sesion para retomarlo; lo ya calculado (p. ej. huellas BLAKE3 en cache) no se repite."""

    def __init__(self, detail: str = "Analisis detenido en un punto seguro") -> None:
        super().__init__(detail)
        self.detail = detail


def stop_point(controller: "TaskController | None", cancel_detail: str = "Operacion cancelada por el usuario") -> None:
    """Punto seguro de parada para motores de analisis: Cancelar o Guardar Pausa."""
    if controller is None:
        return
    state = controller.checkpoint()
    if state == "cancel":
        raise TaskCanceledError(cancel_detail)
    if state == "save_pause":
        raise TaskSaveRequested()


@dataclass(slots=True)
class TaskSessionRecord:
    """Serialized checkpoint of a paused long-running task ready for resumption."""

    session_id: str
    kind: str         # "junk_clean" | "dup_quarantine" | "onedrive_local"
    title: str
    created_at: str
    percent: int
    total_items: int
    processed_items: int
    freed_so_far: int = 0
    pending_paths: list[str] = field(default_factory=list)
    meta: dict[str, Any] = field(default_factory=dict)


class SessionManager:
    """Stores, lists, and deletes resumable task sessions under AppData/WinOptiAI/sessions."""

    def __init__(self, app_dir: Path | None = None) -> None:
        self.sessions_dir = (app_dir or default_app_data_dir()) / "sessions"
        self.sessions_dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def save_session(self, rec: TaskSessionRecord) -> Path:
        target = self.sessions_dir / f"{rec.session_id}.json"
        with self._lock:
            atomic_write_text(target, json.dumps(asdict(rec), ensure_ascii=False))
        return target

    def list_sessions(self) -> list[TaskSessionRecord]:
        with self._lock:
            out: list[TaskSessionRecord] = []
            for fp in sorted(self.sessions_dir.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
                try:
                    raw = json.loads(fp.read_text(encoding="utf-8"))
                    out.append(TaskSessionRecord(**raw))
                except (OSError, json.JSONDecodeError, TypeError):
                    continue
            return out

    def load_session(self, session_id: str) -> TaskSessionRecord | None:
        fp = self.sessions_dir / f"{session_id}.json"
        if not fp.exists():
            return None
        try:
            return TaskSessionRecord(**json.loads(fp.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError, TypeError):
            return None

    def remove_session(self, session_id: str) -> None:
        fp = self.sessions_dir / f"{session_id}.json"
        with self._lock:
            fp.unlink(missing_ok=True)


class TaskController:
    """Thread-safe cooperative pause, save-session, and cancel signal for background workers."""

    def __init__(self, task_id: str | None = None) -> None:
        self.task_id = task_id or uuid.uuid4().hex[:8]
        self._pause_requested = False
        self._save_and_pause_requested = False
        self._cancel_requested = False
        self._lock = threading.Lock()
        self._resume_event = threading.Event()
        self._resume_event.set()

    @property
    def is_paused(self) -> bool:
        with self._lock:
            return self._pause_requested

    @property
    def is_canceled(self) -> bool:
        with self._lock:
            return self._cancel_requested

    @property
    def should_save_checkpoint(self) -> bool:
        with self._lock:
            return self._save_and_pause_requested

    def pause(self) -> None:
        with self._lock:
            self._pause_requested = True
            self._resume_event.clear()

    def pause_and_save(self) -> None:
        with self._lock:
            self._save_and_pause_requested = True
            self._pause_requested = False
            self._resume_event.set()

    def resume(self) -> None:
        with self._lock:
            self._pause_requested = False
            self._resume_event.set()

    def cancel(self) -> None:
        with self._lock:
            self._cancel_requested = True
            self._pause_requested = False
            self._resume_event.set()

    def checkpoint(self) -> str:
        """Block cleanly while paused; return 'cancel' | 'save_pause' | 'ok'."""
        if self.is_canceled:
            return "cancel"
        if self.should_save_checkpoint:
            return "save_pause"
        while self.is_paused:
            if self.is_canceled:
                return "cancel"
            if self.should_save_checkpoint:
                return "save_pause"
            self._resume_event.wait(timeout=0.2)
            time.sleep(0.01)
        if self.is_canceled:
            return "cancel"
        if self.should_save_checkpoint:
            return "save_pause"
        return "ok"


def new_session_id() -> str:
    return f"{datetime.now().astimezone().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}"
