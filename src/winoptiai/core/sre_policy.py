"""Hybrid SRE automation & guardrail policy engine.

Implements best-practice systems engineering rules:
- Continuous lightweight telemetry sampling
- Hysteresis-protected automatic RAM/EcoQoS relief when free physical RAM drops below threshold
- Strict prohibition of silent background file deletion (disk actions remain on-demand/quarantined)
- JSONL structured audit logging for traceability
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
import json
from pathlib import Path
import time

from .i18n import detect_default_language
from .safety_guard import atomic_write_text, default_app_data_dir


def recommended_ram_threshold_gb() -> float:
    """Calibrate RAM pressure threshold dynamically based on total physical RAM."""
    try:
        import psutil

        total_gb = psutil.virtual_memory().total / (1024**3)
        return max(1.2, min(4.0, round(total_gb * 0.115, 1)))
    except Exception:  # noqa: BLE001
        return 1.8


@dataclass(slots=True)
class SREPolicyConfig:
    """User-configurable operational policies persisted locally."""

    auto_ram_relief_enabled: bool = True
    ram_threshold_gb: float = 1.8
    hysteresis_seconds: int = 300
    consecutive_breaches_required: int = 3
    auto_ecoqos_background_browsers: bool = True
    storage_alert_threshold_gb: float = 2.0
    start_minimized_to_tray: bool = False
    active_thermal_profile: str = "balanced"
    theme_mode: str = "dark"       # "dark" | "light"
    language: str = "es"           # "es" | "en" | "pt"
    completed_audit_actions: list[str] = field(default_factory=list)


class SREPolicyEngine:
    """Evaluates telemetry against guardrails and logs all automated/manual interventions."""

    def __init__(self, app_dir: Path | None = None) -> None:
        self.app_dir = app_dir or default_app_data_dir()
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.config_path = self.app_dir / "config.json"
        self.audit_path = self.app_dir / "audit.jsonl"
        self.config = self.load_config()
        self._breach_streak = 0
        self._last_auto_relief_ts = 0.0

    def load_config(self) -> SREPolicyConfig:
        if not self.config_path.exists():
            return SREPolicyConfig(
                ram_threshold_gb=recommended_ram_threshold_gb(),
                language=detect_default_language(),
            )
        try:
            raw = json.loads(self.config_path.read_text(encoding="utf-8"))
            defaults = asdict(
                SREPolicyConfig(
                    ram_threshold_gb=recommended_ram_threshold_gb(),
                    language=detect_default_language(),
                )
            )
            defaults.update({k: v for k, v in raw.items() if k in defaults})
            return SREPolicyConfig(**defaults)
        except (OSError, json.JSONDecodeError, TypeError):
            return SREPolicyConfig()

    def save_config(self, config: SREPolicyConfig | None = None) -> None:
        if config is not None:
            self.config = config
        atomic_write_text(
            self.config_path,
            json.dumps(asdict(self.config), indent=2, ensure_ascii=False),
        )

    def evaluate_ram_pressure(
        self,
        free_ram_gb: float,
        now: float | None = None,
    ) -> bool:
        """Return True only when automatic RAM relief should trigger under SRE hysteresis."""
        if not self.config.auto_ram_relief_enabled:
            self._breach_streak = 0
            return False

        ts = time.monotonic() if now is None else now
        if free_ram_gb < self.config.ram_threshold_gb:
            self._breach_streak += 1
        else:
            self._breach_streak = 0
            return False

        if self._breach_streak < self.config.consecutive_breaches_required:
            return False

        if (ts - self._last_auto_relief_ts) < self.config.hysteresis_seconds:
            self._breach_streak = 0
            return False

        self._last_auto_relief_ts = ts
        self._breach_streak = 0
        return True

    def record_audit_event(
        self,
        actor: str,
        action: str,
        detail: str,
        freed_mb: float = 0.0,
    ) -> None:
        """Append an immutable audit record to audit.jsonl using local system time."""
        entry = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "actor": actor,
            "action": action,
            "detail": detail,
            "freed_mb": round(freed_mb, 2),
        }
        with self.audit_path.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def mark_audit_completed(self, action_id: str) -> None:
        if action_id and action_id not in self.config.completed_audit_actions:
            self.config.completed_audit_actions.append(action_id)
            self.save_config()

    def reset_completed_audits(self) -> None:
        self.config.completed_audit_actions.clear()
        self.save_config()

    def read_recent_audit(self, limit: int = 25) -> list[dict]:
        if not self.audit_path.exists():
            return []
        try:
            lines = self.audit_path.read_text(encoding="utf-8").splitlines()
            parsed = [json.loads(line) for line in lines[-limit:] if line.strip()]
            parsed.reverse()
            return parsed
        except (OSError, json.JSONDecodeError):
            return []
