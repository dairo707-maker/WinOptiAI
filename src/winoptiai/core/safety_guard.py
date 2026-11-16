"""OS protocol safety guardrails and transactional Quarantine Vault.

Guarantees:
- Immutable system path whitelist (Windows, System32, WinSxS, Program Files, drivers)
- Immutable kernel/AV process whitelist (including Bitdefender bdservicehost.exe)
- OneDrive cloud-only placeholder protection
- Windows Restart Manager lock verification
- Reversible Quarantine Vault with SHA-256 manifest
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import uuid

from .win32_bridge import (
    get_locking_processes,
    is_cloud_only_file,
    is_reparse_or_system_file,
    send_to_recycle_bin,
)

# Immutable protected directory prefixes (lowercase normalized)
PROTECTED_PATH_PREFIXES: tuple[str, ...] = (
    "c:\\windows",
    "c:\\program files",
    "c:\\program files (x86)",
    "c:\\programdata\\microsoft",
    "c:\\programdata\\bitdefender",
    "c:\\recovery",
    "c:\\$recycle.bin",
    "c:\\system volume information",
    "c:\\users\\all users",
    "c:\\users\\default",
)

# Exceptions inside C:\Windows / ProgramData explicitly allowed ONLY for residual logs & dumps
EXPLICIT_TEMP_ALLOWLIST: tuple[str, ...] = (
    "c:\\windows\\temp",
    "c:\\windows\\prefetch",
    "c:\\windows\\minidump",
    "c:\\programdata\\microsoft\\windows\\wer\\reportarchive",
    "c:\\programdata\\microsoft\\windows\\wer\\reportqueue",
)

# Critical OS, security, and hardware processes that MUST NEVER be throttled or trimmed
PROTECTED_PROCESS_NAMES: frozenset[str] = frozenset(
    {
        "system",
        "system idle process",
        "registry",
        "memory compression",
        "smss.exe",
        "csrss.exe",
        "wininit.exe",
        "winlogon.exe",
        "services.exe",
        "lsass.exe",
        "lsaiso.exe",
        "svchost.exe",
        "fontdrvhost.exe",
        "dwm.exe",
        "sihost.exe",
        "taskhostw.exe",
        "explorer.exe",
        "shellexperiencehost.exe",
        "startmenuexperiencehost.exe",
        "ctfmon.exe",
        "audiodg.exe",
        "spoolsv.exe",
        "wlanext.exe",
        "securityhealthservice.exe",
        "msmpeng.exe",
        "nissrv.exe",
        # Bitdefender detected on host
        "bdservicehost.exe",
        "bdagent.exe",
        "bdredline.exe",
        "seccenter.exe",
        # Storage & OneDrive integrity
        "onedrive.exe",
        "filecoauth.exe",
        # Self
        "winoptiai.exe",
    }
)


def default_app_data_dir() -> Path:
    base = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    return base / "WinOptiAI"


def is_protected_path(path: str | Path, allow_system_temp: bool = False) -> bool:
    """Return True if path resides inside a protected Windows OS or security directory."""
    try:
        norm = str(Path(path).resolve()).lower()
    except OSError:
        norm = str(path).lower()

    if allow_system_temp:
        for allowed in EXPLICIT_TEMP_ALLOWLIST:
            if norm == allowed or norm.startswith(allowed + "\\"):
                return False

    for prefix in PROTECTED_PATH_PREFIXES:
        if norm == prefix or norm.startswith(prefix + "\\"):
            return True
    return False


def is_safe_to_touch_file(path: str | Path, allow_system_temp: bool = False) -> tuple[bool, str]:
    """Validate OS protocols before reading content or moving a file.

    Returns (is_safe, reason_code).
    """
    p = Path(path)
    if not p.exists():
        return False, "NO_EXISTE"
    if is_protected_path(p, allow_system_temp=allow_system_temp):
        return False, "RUTA_SISTEMA"
    if is_cloud_only_file(p):
        return False, "NUBE_ONEDRIVE"
    if is_reparse_or_system_file(p):
        return False, "SISTEMA_O_ENLACE"

    lockers = get_locking_processes([p])
    if lockers:
        names = ", ".join(str(x["app_name"] or x["pid"]) for x in lockers[:2])
        return False, f"EN_USO ({names})"

    return True, "SEGURO"


def compute_sha256(path: Path) -> str:
    """Compute SHA-256 hex digest for quarantine integrity verification."""
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        while chunk := fh.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


@dataclass(slots=True)
class QuarantineRecord:
    """Manifest record for a single quarantined file or folder."""

    item_id: str
    original_path: str
    vault_path: str
    category: str
    size_bytes: int
    sha256: str
    quarantined_at: str
    is_dir: bool = False


class QuarantineVault:
    """Transactional Quarantine Vault supporting 1-click rollback."""

    def __init__(self, root_dir: Path | None = None) -> None:
        self.root_dir = (root_dir or default_app_data_dir()) / "Quarantine"
        self.items_dir = self.root_dir / "items"
        self.manifest_path = self.root_dir / "manifest.json"
        self.items_dir.mkdir(parents=True, exist_ok=True)

    def _load_manifest(self) -> list[dict]:
        if not self.manifest_path.exists():
            return []
        try:
            data = json.loads(self.manifest_path.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
        except (OSError, json.JSONDecodeError):
            return []

    def _save_manifest(self, records: list[dict]) -> None:
        self.root_dir.mkdir(parents=True, exist_ok=True)
        tmp = self.manifest_path.with_suffix(".tmp")
        tmp.write_text(json.dumps(records, indent=2, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.manifest_path)

    def list_items(self) -> list[QuarantineRecord]:
        return [QuarantineRecord(**item) for item in self._load_manifest()]

    def quarantine_path(
        self,
        source: str | Path,
        category: str,
        allow_system_temp: bool = False,
    ) -> tuple[bool, str, QuarantineRecord | None]:
        """Verify OS safety, move source into Quarantine Vault, and persist manifest."""
        src = Path(source)
        safe, reason = is_safe_to_touch_file(src, allow_system_temp=allow_system_temp)
        if not safe:
            return False, f"Bloqueado por seguridad: {reason}", None

        item_id = uuid.uuid4().hex[:12]
        is_dir = src.is_dir()
        if is_dir:
            size_bytes = sum(f.stat().st_size for f in src.rglob("*") if f.is_file())
            sha256 = "DIRECTORY"
        else:
            size_bytes = src.stat().st_size
            sha256 = compute_sha256(src)

        vault_target = self.items_dir / f"{item_id}__{src.name}"
        try:
            shutil.move(str(src), str(vault_target))
        except OSError as exc:
            return False, f"No se pudo mover a cuarentena: {exc}", None

        record = QuarantineRecord(
            item_id=item_id,
            original_path=str(src.resolve()),
            vault_path=str(vault_target),
            category=category,
            size_bytes=int(size_bytes),
            sha256=sha256,
            quarantined_at=datetime.now().astimezone().isoformat(),
            is_dir=is_dir,
        )
        records = self._load_manifest()
        records.append(asdict(record))
        self._save_manifest(records)
        return True, "Movido a cuarentena con respaldo de restauracion", record

    def restore_item(self, item_id: str) -> tuple[bool, str]:
        """Restore a quarantined file/directory back to its exact original location."""
        records = self._load_manifest()
        match = next((r for r in records if r["item_id"] == item_id), None)
        if not match:
            return False, "Registro no encontrado en el manifiesto de cuarentena"

        vault_path = Path(match["vault_path"])
        original_path = Path(match["original_path"])
        if not vault_path.exists():
            return False, "El archivo fisico ya no existe en la boveda"
        if original_path.exists():
            return False, "Ya existe un archivo en la ruta original de destino"

        if not match.get("is_dir", False) and match.get("sha256") != "DIRECTORY":
            if compute_sha256(vault_path) != match["sha256"]:
                return False, "Fallo de integridad SHA-256 en boveda"

        original_path.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(vault_path), str(original_path))
        updated = [r for r in records if r["item_id"] != item_id]
        self._save_manifest(updated)
        return True, f"Restaurado en {original_path}"

    def purge_item(self, item_id: str, use_recycle_bin: bool = True) -> tuple[bool, str]:
        """Permanently purge or recycle an item from the Quarantine Vault."""
        records = self._load_manifest()
        match = next((r for r in records if r["item_id"] == item_id), None)
        if not match:
            return False, "Registro no encontrado"

        vault_path = Path(match["vault_path"])
        if vault_path.exists():
            if use_recycle_bin and send_to_recycle_bin(vault_path):
                pass
            elif vault_path.is_dir():
                shutil.rmtree(vault_path, ignore_errors=False)
            else:
                vault_path.unlink()

        updated = [r for r in records if r["item_id"] != item_id]
        self._save_manifest(updated)
        return True, "Elemento depurado de la boveda"


class PreOpBackupManager:
    """Creates automatic pre-operation snapshots & power-scheme backups before changes."""

    def __init__(self, root_dir: Path | None = None) -> None:
        self.backups_dir = (root_dir or default_app_data_dir()) / "Backups"
        self.backups_dir.mkdir(parents=True, exist_ok=True)

    def _stamp_dir(self, operation: str) -> Path:
        stamp = datetime.now().astimezone().strftime("%Y%m%d_%H%M%S")
        safe_op = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in operation)
        target = self.backups_dir / f"{stamp}_{safe_op}"
        target.mkdir(parents=True, exist_ok=True)
        return target

    def backup_power_scheme(self, label: str = "power_change") -> Path | None:
        """Export active Windows power plan (.pow) before applying thermal/power tweaks."""
        import subprocess
        from .win32_bridge import IS_WINDOWS

        bdir = self._stamp_dir(label)
        meta = {"created_at": datetime.now().astimezone().isoformat(), "operation": label}
        (bdir / "metadata.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")

        if not IS_WINDOWS:
            return bdir

        pow_file = bdir / "active_scheme_backup.pow"
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        try:
            res = subprocess.run(
                ["powercfg", "/getactivescheme"],
                capture_output=True,
                text=True,
                encoding="oem",
                errors="replace",
                timeout=6,
                creationflags=flags,
            )
            guid = "SCHEME_CURRENT"
            if res.returncode == 0 and ":" in res.stdout:
                parts = res.stdout.split(":", 1)[1].strip().split()
                if parts:
                    guid = parts[0]
            subprocess.run(
                ["powercfg", "/export", str(pow_file), guid],
                capture_output=True,
                timeout=8,
                creationflags=flags,
            )
        except (OSError, subprocess.SubprocessError):
            pass
        return bdir

    def create_operation_snapshot(self, operation: str, items: list[dict]) -> Path:
        """Persist a JSON rollback/audit manifest of affected targets prior to execution."""
        bdir = self._stamp_dir(operation)
        payload = {
            "created_at": datetime.now().astimezone().isoformat(),
            "operation": operation,
            "item_count": len(items),
            "items": items[:500],
        }
        (bdir / "snapshot.json").write_text(
            json.dumps(payload, indent=2, ensure_ascii=False),
            encoding="utf-8",
        )
        return bdir

    def restore_latest_power_backup(self) -> tuple[bool, str]:
        """Import and activate the most recent exported .pow power scheme backup."""
        import subprocess
        from .win32_bridge import IS_WINDOWS

        if not IS_WINDOWS:
            return False, "Solo disponible en Windows"
        pow_files = sorted(self.backups_dir.glob("*/*.pow"), reverse=True)
        if not pow_files:
            return False, "No hay copias previas de plan de energia (.pow)."

        latest = pow_files[0]
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
        res = subprocess.run(
            ["powercfg", "/import", str(latest)],
            capture_output=True,
            text=True,
            encoding="oem",
            errors="replace",
            timeout=8,
            creationflags=flags,
        )
        if res.returncode == 0:
            return True, f"Plan de energia restaurado desde respaldo: {latest.parent.name}"
        return False, f"No se pudo importar respaldo .pow: {res.stderr.strip()}"
