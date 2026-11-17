"""Historial local y acotado de metricas del equipo (v0.5.7).

- Un registro por minuto (RAM libre, CPU %, temperatura si hay, disco libre, RAM de la app)
  en ``%LOCALAPPDATA%\\WinOptiAI\\metrics.sqlite``. Retencion maxima: 7 dias (~10 080 filas).
- Todas las lecturas y escrituras se hacen fuera del hilo GUI (``MetricsHistory.submit``),
  con una sola hebra trabajadora para que SQLite nunca tenga escrituras concurrentes.
- Eventos de ``audit.jsonl`` clasificados para marcarlos sobre la linea de tiempo y para el
  acumulado de espacio liberado por tipo.

Modulo sin dependencias de Qt (probado en ``tests/test_v057_metrics_history.py``).
"""

from __future__ import annotations

from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
import sqlite3
import threading
import time
from typing import Any, Callable

from .safety_guard import default_app_data_dir

RETENTION_SECONDS = 7 * 24 * 3600
SAMPLE_INTERVAL_SECONDS = 60
MAX_CHART_POINTS = 720  # 24 h a 2 min o 7 d a ~14 min: suficiente para 1 px por punto
AUDIT_TAIL_BYTES = 4 * 1024 * 1024

RANGE_24H = 24 * 3600
RANGE_7D = RETENTION_SECONDS

# Categorias de marcadores sobre la linea de tiempo.
EVENT_BOOST = "boost"
EVENT_CLEAN = "limpieza"
EVENT_PURGE = "depuracion"
EVENT_ERROR = "error"

# Tipos del acumulado de espacio liberado (disco, no RAM).
FREED_TEMP = "temporales"
FREED_DUPS = "duplicados"
FREED_QUARANTINE = "cuarentena"
FREED_ONEDRIVE = "onedrive"
FREED_KINDS = (FREED_TEMP, FREED_DUPS, FREED_QUARANTINE, FREED_ONEDRIVE)

_FREED_BY_ACTION: dict[str, str] = {
    "limpieza temporales": FREED_TEMP,
    "reanudacion sesion": FREED_TEMP,
    "duplicados blake3": FREED_DUPS,
    "autolimpieza duplicados": FREED_DUPS,
    "hardlink ntfs": FREED_DUPS,
    "depuracion cuarentena": FREED_QUARANTINE,
    "auto-expiracion cuarentena (30d)": FREED_QUARANTINE,
    "cuarentena por formato": FREED_QUARANTINE,
    "cuarentena huerfanos": FREED_QUARANTINE,
    "onedrive solo nube": FREED_ONEDRIVE,
    "onedrive nube papelera": FREED_ONEDRIVE,
}


@dataclass(slots=True)
class MetricSample:
    ts: int  # epoch (s)
    ram_free_gb: float
    ram_total_gb: float
    cpu_pct: float
    cpu_temp_c: float | None
    disk_free_gb: float | None
    app_ram_mb: float | None


@dataclass(slots=True)
class AuditEvent:
    ts: float  # epoch (s)
    actor: str
    action: str
    detail: str
    freed_mb: float
    category: str | None  # EVENT_* o None (no se marca en la linea de tiempo)
    freed_kind: str | None  # FREED_* o None (no cuenta como espacio en disco)


def classify_event(actor: str, action: str) -> str | None:
    """Categoria de marcador para un registro de auditoria (None = no se dibuja)."""
    a = action.strip().lower()
    if a == "ai boost":
        return EVENT_BOOST
    if actor == "crash_guard" or "informe de error" in a or "cierre inesperado" in a:
        return EVENT_ERROR
    if a.startswith("depuracion cuarentena") or a.startswith("auto-expiracion cuarentena"):
        return EVENT_PURGE
    if a in _FREED_BY_ACTION:
        return EVENT_CLEAN
    return None


def freed_kind_for(action: str) -> str | None:
    return _FREED_BY_ACTION.get(action.strip().lower())


def _parse_ts(raw: str) -> float | None:
    try:
        return datetime.fromisoformat(raw).timestamp()
    except (TypeError, ValueError):
        return None


def load_audit_events(audit_path: Path, since_ts: float = 0.0) -> list[AuditEvent]:
    """Leer ``audit.jsonl`` (solo la cola, maximo 4 MB) y devolver eventos desde ``since_ts``.

    Las lineas duplicadas exactas (mismo instante, accion y detalle) se cuentan una sola vez:
    ``audit.jsonl`` de versiones previas a v0.5.7 puede contener duplicados de dos instancias.
    """
    if not audit_path.exists():
        return []
    try:
        with audit_path.open("rb") as fh:
            fh.seek(0, 2)
            size = fh.tell()
            fh.seek(max(0, size - AUDIT_TAIL_BYTES))
            raw = fh.read()
    except OSError:
        return []
    text = raw.decode("utf-8", errors="replace")
    if len(raw) >= AUDIT_TAIL_BYTES:
        text = text.split("\n", 1)[-1]  # descartar la primera linea posiblemente cortada
    out: list[AuditEvent] = []
    seen: set[tuple[str, str, str, str]] = set()
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        if not isinstance(rec, dict):
            continue
        key = (str(rec.get("timestamp", "")), str(rec.get("actor", "")), str(rec.get("action", "")), str(rec.get("detail", "")))
        if key in seen:
            continue
        seen.add(key)
        ts = _parse_ts(key[0])
        if ts is None or ts < since_ts:
            continue
        actor, action = key[1], key[2]
        try:
            freed = float(rec.get("freed_mb", 0.0) or 0.0)
        except (TypeError, ValueError):
            freed = 0.0
        out.append(
            AuditEvent(
                ts=ts,
                actor=actor,
                action=action,
                detail=key[3],
                freed_mb=freed,
                category=classify_event(actor, action),
                freed_kind=freed_kind_for(action),
            )
        )
    out.sort(key=lambda e: e.ts)
    return out


def freed_totals_by_kind(events: list[AuditEvent]) -> dict[str, float]:
    """MB liberados en disco por tipo (AI Boost libera RAM y no cuenta aqui)."""
    totals = {k: 0.0 for k in FREED_KINDS}
    for ev in events:
        if ev.freed_kind and ev.freed_mb > 0:
            totals[ev.freed_kind] += ev.freed_mb
    return totals


def freed_cumulative_series(events: list[AuditEvent]) -> dict[str, list[tuple[float, float]]]:
    """Series escalonadas (ts, MB acumulados) por tipo, para el grafico de area apilada."""
    series: dict[str, list[tuple[float, float]]] = {k: [] for k in FREED_KINDS}
    acc = {k: 0.0 for k in FREED_KINDS}
    for ev in events:
        if ev.freed_kind and ev.freed_mb > 0:
            acc[ev.freed_kind] += ev.freed_mb
            series[ev.freed_kind].append((ev.ts, acc[ev.freed_kind]))
    return series


class MetricsStore:
    """Almacen SQLite acotado (una conexion por operacion; seguro entre hilos)."""

    def __init__(self, db_path: Path | None = None) -> None:
        self.db_path = db_path or (default_app_data_dir() / "metrics.sqlite")
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        with self._connect() as con:
            con.execute(
                "CREATE TABLE IF NOT EXISTS samples ("
                " ts INTEGER PRIMARY KEY,"
                " ram_free_gb REAL NOT NULL,"
                " ram_total_gb REAL NOT NULL,"
                " cpu_pct REAL NOT NULL,"
                " cpu_temp_c REAL,"
                " disk_free_gb REAL,"
                " app_ram_mb REAL)"
            )

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(str(self.db_path), timeout=5.0)
        con.execute("PRAGMA journal_mode=WAL")
        con.execute("PRAGMA synchronous=NORMAL")
        return con

    def add(self, sample: MetricSample, now: float | None = None) -> None:
        cutoff = int((now if now is not None else time.time()) - RETENTION_SECONDS)
        with self._lock, self._connect() as con:
            con.execute(
                "INSERT OR REPLACE INTO samples VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    int(sample.ts),
                    float(sample.ram_free_gb),
                    float(sample.ram_total_gb),
                    float(sample.cpu_pct),
                    sample.cpu_temp_c,
                    sample.disk_free_gb,
                    sample.app_ram_mb,
                ),
            )
            con.execute("DELETE FROM samples WHERE ts < ?", (cutoff,))

    def count(self) -> int:
        with self._connect() as con:
            return int(con.execute("SELECT COUNT(*) FROM samples").fetchone()[0])

    def query(self, range_seconds: int, now: float | None = None, max_points: int = MAX_CHART_POINTS) -> list[MetricSample]:
        """Muestras del rango, promediadas por cubetas para no superar ``max_points``."""
        end = now if now is not None else time.time()
        start = int(end - range_seconds)
        bucket = max(SAMPLE_INTERVAL_SECONDS, int(range_seconds / max(1, max_points)))
        with self._connect() as con:
            rows = con.execute(
                "SELECT MIN(ts), AVG(ram_free_gb), MAX(ram_total_gb), AVG(cpu_pct), AVG(cpu_temp_c),"
                " AVG(disk_free_gb), AVG(app_ram_mb)"
                " FROM samples WHERE ts >= ? GROUP BY ts / ? ORDER BY 1",
                (start, bucket),
            ).fetchall()
        return [
            MetricSample(int(r[0]), float(r[1]), float(r[2]), float(r[3]), r[4], r[5], r[6])
            for r in rows
        ]


class MinuteAggregator:
    """Promedia lecturas de 2 s y entrega una muestra por minuto (sin depender de Qt)."""

    def __init__(self, interval: int = SAMPLE_INTERVAL_SECONDS) -> None:
        self.interval = interval
        self._started: float | None = None
        self._ram: list[float] = []
        self._cpu: list[float] = []
        self._temp: list[float] = []
        self._total = 0.0

    def add(self, ram_free_gb: float, ram_total_gb: float, cpu_pct: float, cpu_temp_c: float | None, now: float | None = None) -> dict[str, Any] | None:
        ts = time.time() if now is None else now
        if self._started is None:
            self._started = ts
        self._ram.append(float(ram_free_gb))
        self._cpu.append(float(cpu_pct))
        if cpu_temp_c is not None:
            self._temp.append(float(cpu_temp_c))
        self._total = float(ram_total_gb)
        if ts - self._started < self.interval:
            return None
        out = {
            "ts": int(ts),
            "ram_free_gb": round(sum(self._ram) / len(self._ram), 3),
            "ram_total_gb": self._total,
            "cpu_pct": round(sum(self._cpu) / len(self._cpu), 2),
            "cpu_temp_c": round(sum(self._temp) / len(self._temp), 1) if self._temp else None,
        }
        self._started = ts
        self._ram.clear()
        self._cpu.clear()
        self._temp.clear()
        return out


class MetricsHistory:
    """Fachada: hebra unica para SQLite + audit.jsonl, siempre fuera del hilo GUI."""

    def __init__(self, app_dir: Path | None = None) -> None:
        self.app_dir = app_dir or default_app_data_dir()
        self.store = MetricsStore(self.app_dir / "metrics.sqlite")
        self.audit_path = self.app_dir / "audit.jsonl"
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="winoptiai-metrics")

    def submit(self, fn: Callable[..., Any], *args: Any) -> Future:
        return self._executor.submit(fn, *args)

    def record_async(self, partial: dict[str, Any]) -> Future:
        """Completar disco libre y RAM de la app en la hebra trabajadora y guardar."""
        return self.submit(self._record, dict(partial))

    def _record(self, partial: dict[str, Any]) -> MetricSample:
        import os

        import psutil

        disk_free: float | None
        try:
            disk_free = round(psutil.disk_usage(os.environ.get("SystemDrive", "C:") + "\\").free / (1024**3), 2)
        except OSError:
            disk_free = None
        try:
            app_mb: float | None = round(psutil.Process().memory_info().rss / (1024 * 1024), 1)
        except (psutil.Error, OSError):
            app_mb = None
        sample = MetricSample(
            ts=int(partial["ts"]),
            ram_free_gb=float(partial["ram_free_gb"]),
            ram_total_gb=float(partial["ram_total_gb"]),
            cpu_pct=float(partial["cpu_pct"]),
            cpu_temp_c=partial.get("cpu_temp_c"),
            disk_free_gb=disk_free,
            app_ram_mb=app_mb,
        )
        self.store.add(sample)
        return sample

    def load_snapshot(self, range_seconds: int) -> dict[str, Any]:
        """Datos para los graficos (ejecutar via ``submit``)."""
        now = time.time()
        samples = self.store.query(range_seconds, now=now)
        events = load_audit_events(self.audit_path, since_ts=0.0)
        in_range = [e for e in events if e.ts >= now - range_seconds]
        return {
            "now": now,
            "range": range_seconds,
            "samples": samples,
            "events": [e for e in in_range if e.category],
            "freed_events_all": [e for e in events if e.freed_kind and e.freed_mb > 0],
            "freed_totals": freed_totals_by_kind(in_range),
            "freed_totals_all": freed_totals_by_kind(events),
        }

    def shutdown(self) -> None:
        self._executor.shutdown(wait=False, cancel_futures=True)
