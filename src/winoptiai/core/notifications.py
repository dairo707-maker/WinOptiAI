"""Persistent notification center and low-noise periodic optimization advisor."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime
import json
from pathlib import Path
import time
import uuid

from .safety_guard import default_app_data_dir


@dataclass(slots=True)
class NotificationItem:
    """Single notification or periodic optimization suggestion."""

    notif_id: str
    timestamp: str
    kind: str         # "COMPLETADO" | "SUGERENCIA" | "AVISO" | "ERROR"
    title: str
    detail: str
    read: bool = False
    action_tab: int | None = None


class NotificationCenter:
    """Thread-safe local JSON store for user-dismissible notifications."""

    def __init__(self, app_dir: Path | None = None, max_items: int = 80) -> None:
        self.app_dir = app_dir or default_app_data_dir()
        self.app_dir.mkdir(parents=True, exist_ok=True)
        self.file_path = self.app_dir / "notifications.json"
        self.max_items = max_items
        self._items: list[NotificationItem] = self._load()

    def _load(self) -> list[NotificationItem]:
        if not self.file_path.exists():
            return []
        try:
            raw = json.loads(self.file_path.read_text(encoding="utf-8"))
            if not isinstance(raw, list):
                return []
            return [NotificationItem(**entry) for entry in raw]
        except (OSError, json.JSONDecodeError, TypeError):
            return []

    def _save(self) -> None:
        tmp = self.file_path.with_suffix(".tmp")
        tmp.write_text(
            json.dumps([asdict(x) for x in self._items], indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        tmp.replace(self.file_path)

    def list_items(self) -> list[NotificationItem]:
        return list(self._items)

    def unread_count(self) -> int:
        return sum(1 for item in self._items if not item.read)

    def add(
        self,
        kind: str,
        title: str,
        detail: str,
        action_tab: int | None = None,
    ) -> NotificationItem:
        item = NotificationItem(
            notif_id=uuid.uuid4().hex[:10],
            timestamp=datetime.now().astimezone().strftime("%Y-%m-%d %H:%M:%S"),
            kind=kind,
            title=title,
            detail=detail,
            read=False,
            action_tab=action_tab,
        )
        self._items.insert(0, item)
        self._items = self._items[: self.max_items]
        self._save()
        return item

    def mark_all_read(self) -> None:
        changed = False
        for item in self._items:
            if not item.read:
                item.read = True
                changed = True
        if changed:
            self._save()

    def remove(self, notif_id: str) -> bool:
        before = len(self._items)
        self._items = [x for x in self._items if x.notif_id != notif_id]
        if len(self._items) != before:
            self._save()
            return True
        return False

    def clear_all(self) -> None:
        self._items.clear()
        self._save()


class PeriodicAdvisor:
    """Low-frequency optimization advisor (checks relevant changes with long cooldowns)."""

    def __init__(self, cooldown_seconds: int = 7200) -> None:
        self.cooldown_seconds = cooldown_seconds
        self._last_sent: dict[str, float] = {}

    def _can_emit(self, category: str, now: float) -> bool:
        prev = self._last_sent.get(category, -1e9)
        if (now - prev) >= self.cooldown_seconds:
            self._last_sent[category] = now
            return True
        return False

    def evaluate(
        self,
        free_ram_gb: float,
        ram_threshold_gb: float,
        temp_junk_gb: float,
        zombie_count: int,
        zombie_ram_mb: float,
        now: float | None = None,
    ) -> list[dict]:
        """Return only relevant, high-signal optimization suggestions (never spam)."""
        ts = time.monotonic() if now is None else now
        suggestions: list[dict] = []

        if temp_junk_gb >= 1.5 and self._can_emit("junk", ts):
            suggestions.append(
                {
                    "title": "Temporales acumulando espacio",
                    "detail": (
                        f"Se detectaron {temp_junk_gb:.2f} GB en archivos temporales seguros. "
                        "Puedes revisarlos y depurarlos en Almacenamiento."
                    ),
                    "action_tab": 1,
                }
            )

        if zombie_count >= 2 and zombie_ram_mb >= 200.0 and self._can_emit("zombies", ts):
            suggestions.append(
                {
                    "title": "Workers MCP / Node huerfanos",
                    "detail": (
                        f"Hay {zombie_count} procesos huerfanos reteniendo {zombie_ram_mb:.0f} MB de RAM. "
                        "Revisa el Cazador MCP en Procesos e IA."
                    ),
                    "action_tab": 2,
                }
            )

        if free_ram_gb < ram_threshold_gb and self._can_emit("ram", ts):
            suggestions.append(
                {
                    "title": "Memoria libre ajustada para IA",
                    "detail": (
                        f"Quedan {free_ram_gb:.2f} GB libres (umbral {ram_threshold_gb:.1f} GB). "
                        "Ejecuta AI Boost para compactar Working Set sin cerrar aplicaciones."
                    ),
                    "action_tab": 0,
                }
            )

        return suggestions
