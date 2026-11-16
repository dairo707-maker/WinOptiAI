"""Process, RAM, and Agentic AI workload optimizer for Windows 11.

Provides:
- Live system memory & CPU telemetry
- AI Boost (EcoQoS throttling for background clutter + safe Working Set trimming)
- Local AI memory preparation (freeing contiguous physical RAM for Iris Xe shared VRAM)
- Orphan AI/MCP worker detection (stale node.exe / python.exe / uv.exe with dead parent)
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from typing import Callable
import psutil

from ..core.safety_guard import PROTECTED_PROCESS_NAMES
from ..core.win32_bridge import get_foreground_pid, set_process_ecoqos, trim_process_working_set


# Active coding & AI agent processes whose foreground responsiveness is preserved
AI_FOREGROUND_AGENTS: frozenset[str] = frozenset(
    {
        "antigravity.exe",
        "claude.exe",
        "code.exe",
        "cursor.exe",
        "language_server.exe",
        "ollama.exe",
        "ollama_app.exe",
        "lm studio.exe",
        "python.exe",
        "uv.exe",
    }
)

# Secondary processes safe to move into Windows 11 EcoQoS + trim working set
ECOQOS_ELIGIBLE_NAMES: frozenset[str] = frozenset(
    {
        "chrome.exe",
        "msedge.exe",
        "firefox.exe",
        "teams.exe",
        "ms-teams.exe",
        "slack.exe",
        "discord.exe",
        "spotify.exe",
        "searchindexer.exe",
        "searchhost.exe",
        "widgetservice.exe",
        "widgets.exe",
        "phoneexperiencehost.exe",
        "yourphone.exe",
        "adobeipcbroker.exe",
        "ccxprocess.exe",
        "lenovovantage.exe",
        "onedrive.standaloneupdater.exe",
    }
)

ZOMBIE_AI_WORKER_NAMES: frozenset[str] = frozenset(
    {
        "node.exe",
        "python.exe",
        "uv.exe",
        "npx.exe",
    }
)


@dataclass(slots=True)
class ProcessEntry:
    """Snapshot of a running Windows process relevant to RAM and AI performance."""

    pid: int
    name: str
    ram_mb: float
    cpu_pct: float
    role: str        # "AGENTE_IA" | "SISTEMA" | "SEGUNDO_PLANO" | "ZOMBI_MCP" | "USUARIO"
    ecoqos_eligible: bool


@dataclass(slots=True)
class ZombieWorker:
    """Orphaned Node/Python/uv worker holding memory after its parent terminated."""

    pid: int
    name: str
    ppid: int
    ram_mb: float
    cmdline: str


def get_memory_snapshot() -> dict[str, float]:
    """Return current Windows physical and swap memory metrics in GB and percentages."""
    vm = psutil.virtual_memory()
    return {
        "total_gb": round(vm.total / (1024**3), 2),
        "used_gb": round(vm.used / (1024**3), 2),
        "free_gb": round(vm.available / (1024**3), 2),
        "used_pct": float(vm.percent),
    }


_PROC_CACHE: dict[int, psutil.Process] = {}


def list_top_processes(limit: int = 35) -> list[ProcessEntry]:
    """Enumerate running processes sorted by Working Set RAM usage with live cached CPU%."""
    entries: list[ProcessEntry] = []
    seen_pids: set[int] = set()
    for proc in psutil.process_iter(["pid", "name", "memory_info"]):
        try:
            pid = int(proc.info["pid"])
            name = (proc.info["name"] or "").strip()
            if not name or pid <= 4:
                continue
            seen_pids.add(pid)
            cached = _PROC_CACHE.get(pid)
            if cached is None:
                _PROC_CACHE[pid] = proc
                cpu_pct = round(float(proc.cpu_percent(interval=None) or 0.0), 1)
            else:
                cpu_pct = round(float(cached.cpu_percent(interval=None) or 0.0), 1)
            mem = proc.info.get("memory_info")
            ram_mb = round((mem.rss if mem else 0) / (1024 * 1024), 1)
            lname = name.lower()

            if lname in PROTECTED_PROCESS_NAMES:
                role = "SISTEMA"
                eligible = False
            elif lname in AI_FOREGROUND_AGENTS:
                role = "AGENTE_IA"
                eligible = False
            elif lname in ECOQOS_ELIGIBLE_NAMES:
                role = "SEGUNDO_PLANO"
                eligible = True
            else:
                role = "USUARIO"
                eligible = ram_mb >= 80.0

            entries.append(
                ProcessEntry(
                    pid=pid,
                    name=name,
                    ram_mb=ram_mb,
                    cpu_pct=cpu_pct,
                    role=role,
                    ecoqos_eligible=eligible,
                )
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    entries.sort(key=lambda e: e.ram_mb, reverse=True)
    for stale_pid in list(_PROC_CACHE.keys()):
        if stale_pid not in seen_pids:
            _PROC_CACHE.pop(stale_pid, None)
    return entries[:limit]


def detect_orphan_ai_workers(min_ram_mb: float = 35.0) -> list[ZombieWorker]:
    """Detect orphaned node/python/uv MCP workers whose parent PID no longer exists."""
    live_pids = set(psutil.pids())
    zombies: list[ZombieWorker] = []

    for proc in psutil.process_iter(["pid", "name"]):
        try:
            pid = int(proc.info["pid"])
            name = (proc.info["name"] or "").strip()
            lname = name.lower()
            if lname not in ZOMBIE_AI_WORKER_NAMES or pid <= 4:
                continue

            ppid = int(proc.ppid() or 0)
            mem = proc.memory_info()
            ram_mb = round((mem.rss if mem else 0) / (1024 * 1024), 1)
            if ram_mb < min_ram_mb:
                continue

            # Parent is dead (not PID 0/4 and absent from live PIDs) & process is idle
            parent_dead = ppid > 4 and ppid not in live_pids
            if not parent_dead:
                continue
            cpu = float(proc.cpu_percent(interval=None))
            if cpu < 1.0:
                cmd = " ".join(proc.cmdline() or [])
                if len(cmd) > 140:
                    cmd = cmd[:137] + "..."
                zombies.append(
                    ZombieWorker(
                        pid=pid,
                        name=name,
                        ppid=ppid,
                        ram_mb=ram_mb,
                        cmdline=cmd or name,
                    )
                )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    zombies.sort(key=lambda z: z.ram_mb, reverse=True)
    return zombies


def run_ai_boost(
    trim_heavy_apps: bool = True,
    apply_ecoqos: bool = True,
    min_ram_mb_to_trim: float = 120.0,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, float | int]:
    """Execute safe RAM compaction & EcoQoS throttling for Agentic AI workloads.

    Never kills user apps or touches protected OS/security processes.
    """
    before = get_memory_snapshot()["free_gb"]
    fg_pid = get_foreground_pid()
    self_pid = os.getpid()
    ecoqos_count = 0
    trimmed_count = 0

    procs = list(psutil.process_iter(["pid", "name", "memory_info"]))
    total_procs = max(1, len(procs))
    for idx, proc in enumerate(procs, start=1):
        if progress_cb and idx % 15 == 0:
            progress_cb(10 + int(idx * 85 / total_procs), "Aplicando EcoQoS y compactando RAM...")
        try:
            pid = int(proc.info["pid"])
            name = (proc.info["name"] or "").strip().lower()
            if (
                not name
                or pid <= 4
                or pid == self_pid
                or (fg_pid is not None and pid == fg_pid)
                or name in PROTECTED_PROCESS_NAMES
                or name in AI_FOREGROUND_AGENTS
            ):
                continue

            mem = proc.info.get("memory_info")
            ram_mb = (mem.rss if mem else 0) / (1024 * 1024)

            if apply_ecoqos and name in ECOQOS_ELIGIBLE_NAMES:
                if set_process_ecoqos(pid, enable=True):
                    ecoqos_count += 1

            # Compact inactive working-set pages on heavy background & Electron apps
            if trim_heavy_apps and ram_mb >= min_ram_mb_to_trim:
                if trim_process_working_set(pid):
                    trimmed_count += 1
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    after = get_memory_snapshot()["free_gb"]
    delta_mb = max(0.0, round((after - before) * 1024.0, 1))
    return {
        "free_before_gb": before,
        "free_after_gb": after,
        "freed_mb": delta_mb,
        "ecoqos_applied": ecoqos_count,
        "trimmed_processes": trimmed_count,
    }


def terminate_zombie_worker(pid: int) -> tuple[bool, str]:
    """Safely terminate a confirmed orphaned AI/MCP worker process."""
    try:
        proc = psutil.Process(pid)
        lname = proc.name().lower()
        if lname in PROTECTED_PROCESS_NAMES or lname not in ZOMBIE_AI_WORKER_NAMES:
            return False, "Proceso protegido no elegible"
        proc.terminate()
        proc.wait(timeout=3)
        return True, f"Proceso {lname} ({pid}) finalizado"
    except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.TimeoutExpired) as exc:
        return False, f"No se pudo finalizar PID {pid}: {exc}"
