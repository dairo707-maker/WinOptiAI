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
import time
from typing import Callable
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


def is_safe_to_touch_file(
    path: str | Path,
    allow_system_temp: bool = False,
    skip_lock_check: bool = False,
) -> tuple[bool, str]:
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

    if not skip_lock_check:
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
        import threading

        self._lock = threading.Lock()
        self.root_dir = (root_dir or default_app_data_dir()) / "Quarantine"
        self.items_dir = self.root_dir / "items"
        self.manifest_path = self.root_dir / "manifest.json"
        self.items_dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _move_fast(src: Path, dst: Path) -> None:
        dst.parent.mkdir(parents=True, exist_ok=True)
        try:
            os.replace(src, dst)
        except OSError:
            shutil.move(str(src), str(dst))

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
        for attempt in range(5):
            try:
                tmp.replace(self.manifest_path)
                return
            except PermissionError:
                if attempt == 4:
                    raise
                time.sleep(0.06 * (attempt + 1))

    def list_items(self) -> list[QuarantineRecord]:
        with self._lock:
            return [QuarantineRecord(**item) for item in self._load_manifest()]

    def quarantine_path(
        self,
        source: str | Path,
        category: str,
        allow_system_temp: bool = False,
        skip_lock_check: bool = False,
    ) -> tuple[bool, str, QuarantineRecord | None]:
        """Verify OS safety, move source into Quarantine Vault, and persist manifest."""
        src = Path(source)
        safe, reason = is_safe_to_touch_file(
            src,
            allow_system_temp=allow_system_temp,
            skip_lock_check=skip_lock_check,
        )
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
            self._move_fast(src, vault_target)
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
        with self._lock:
            records = self._load_manifest()
            records.append(asdict(record))
            self._save_manifest(records)
        return True, "Movido a cuarentena con respaldo de restauracion", record

    def quarantine_many(
        self,
        entries: list[tuple[Path, str]],
        allow_system_temp: bool = False,
        skip_lock_check: bool = False,
        compute_hashes: bool = True,
        progress_cb: Callable[[int, str], None] | None = None,
    ) -> dict[str, int]:
        """Move multiple individual paths in one manifest transaction (O(N) instead of O(N^2))."""
        moved = 0
        skipped = 0
        perm_denied = 0
        freed_bytes = 0
        new_records: list[dict] = []
        total = max(1, len(entries))
        now_iso = datetime.now().astimezone().isoformat()

        for idx, (src, category) in enumerate(entries, start=1):
            if progress_cb and (idx == 1 or idx % 20 == 0 or idx == total):
                pct = 10 + int(idx * 85 / total)
                progress_cb(pct, f"Respaldando en cuarentena ({idx}/{total})...")
            safe, reason = is_safe_to_touch_file(
                src,
                allow_system_temp=allow_system_temp,
                skip_lock_check=skip_lock_check,
            )
            if not safe:
                if "Permiso" in reason or "EN_USO" in reason:
                    perm_denied += 1
                skipped += 1
                continue
            item_id = uuid.uuid4().hex[:12]
            try:
                is_dir = src.is_dir()
                if is_dir:
                    size_bytes = sum(f.stat().st_size for f in src.rglob("*") if f.is_file())
                    sha256 = "DIRECTORY"
                else:
                    size_bytes = src.stat().st_size
                    sha256 = compute_sha256(src) if compute_hashes else "FAST_SKIP"
                vault_target = self.items_dir / f"{item_id}__{src.name}"
                orig_resolved = str(src.resolve())
                self._move_fast(src, vault_target)
            except PermissionError:
                perm_denied += 1
                skipped += 1
                continue
            except OSError:
                skipped += 1
                continue

            moved += 1
            freed_bytes += int(size_bytes)
            new_records.append(
                asdict(
                    QuarantineRecord(
                        item_id=item_id,
                        original_path=orig_resolved,
                        vault_path=str(vault_target),
                        category=category,
                        size_bytes=int(size_bytes),
                        sha256=sha256,
                        quarantined_at=now_iso,
                        is_dir=is_dir,
                    )
                )
            )

        if new_records:
            with self._lock:
                records = self._load_manifest()
                records.extend(new_records)
                self._save_manifest(records)
        return {
            "moved": moved,
            "skipped": skipped,
            "permission_denied": perm_denied,
            "freed_bytes": freed_bytes,
        }

    def quarantine_batch_bundle(
        self,
        sources: list[tuple[Path, int]],
        base_dir: Path,
        bundle_name: str,
        category: str,
        allow_system_temp: bool = False,
        progress_cb: Callable[[int, str], None] | None = None,
    ) -> dict[str, int]:
        """Move thousands of disposable/temp files into ONE reversible batch bundle in O(N) time."""
        if not sources:
            return {"moved": 0, "skipped": 0, "permission_denied": 0, "freed_bytes": 0}

        if is_protected_path(base_dir, allow_system_temp=allow_system_temp):
            return {"moved": 0, "skipped": len(sources), "permission_denied": 0, "freed_bytes": 0}

        batch_id = uuid.uuid4().hex[:12]
        safe_slug = "".join(ch if ch.isalnum() or ch in ("-", "_") else "_" for ch in bundle_name)[:40]
        bundle_dir = self.items_dir / f"batch_{batch_id}__{safe_slug}"
        files_dir = bundle_dir / "files"
        files_dir.mkdir(parents=True, exist_ok=True)

        moved = 0
        skipped = 0
        perm_denied = 0
        freed_bytes = 0
        total = max(1, len(sources))
        base_resolved = base_dir.resolve()
        base_str = str(base_resolved)
        base_prefix_low = base_str.lower() + "\\"
        files_dir_str = str(files_dir)
        made_dirs: set[str] = {files_dir_str}
        bundle_entries: list[list[str]] = []

        for idx, (src, est_size) in enumerate(sources, start=1):
            if progress_cb and (idx == 1 or idx % 250 == 0 or idx == total):
                pct = 15 + int(idx * 80 / total)
                progress_cb(pct, f"Moviendo a respaldo seguro ({idx}/{total})...")
            try:
                src_abs = os.path.abspath(str(src))
                if not src_abs.lower().startswith(base_prefix_low):
                    if is_protected_path(src, allow_system_temp=allow_system_temp):
                        skipped += 1
                        continue
                    rel_str = f"item_{idx}_{src.name}"
                else:
                    rel_str = os.path.relpath(src_abs, base_str)
                dst_str = os.path.join(files_dir_str, rel_str)
                dst_parent = os.path.dirname(dst_str)
                if dst_parent not in made_dirs:
                    os.makedirs(dst_parent, exist_ok=True)
                    made_dirs.add(dst_parent)
                try:
                    os.replace(src_abs, dst_str)
                except OSError:
                    shutil.move(src_abs, dst_str)
                bundle_entries.append([rel_str, src_abs])
                moved += 1
                freed_bytes += int(est_size)
            except PermissionError:
                perm_denied += 1
                skipped += 1
            except OSError:
                skipped += 1

        if moved == 0:
            shutil.rmtree(bundle_dir, ignore_errors=True)
            return {
                "moved": 0,
                "skipped": skipped,
                "permission_denied": perm_denied,
                "freed_bytes": 0,
            }

        bundle_meta = bundle_dir / "_bundle_manifest.json"
        bundle_meta.write_text(json.dumps(bundle_entries, ensure_ascii=False), encoding="utf-8")

        record = QuarantineRecord(
            item_id=batch_id,
            original_path=f"{base_resolved} ({moved} archivos)",
            vault_path=str(bundle_dir),
            category=category,
            size_bytes=int(freed_bytes),
            sha256=f"BATCH:{moved}",
            quarantined_at=datetime.now().astimezone().isoformat(),
            is_dir=True,
        )
        with self._lock:
            records = self._load_manifest()
            records.append(asdict(record))
            self._save_manifest(records)
        return {
            "moved": moved,
            "skipped": skipped,
            "permission_denied": perm_denied,
            "freed_bytes": freed_bytes,
        }

    def restore_item(self, item_id: str) -> tuple[bool, str]:
        """Restore a quarantined file, directory, or batch bundle back to original locations."""
        with self._lock:
            records = self._load_manifest()
            match = next((r for r in records if r["item_id"] == item_id), None)
        if not match:
            return False, "Registro no encontrado en el manifiesto de cuarentena"

        vault_path = Path(match["vault_path"])
        if not vault_path.exists():
            return False, "El archivo fisico ya no existe en la boveda"

        sha_tag = str(match.get("sha256") or "")
        bundle_meta = vault_path / "_bundle_manifest.json"
        if sha_tag.startswith("BATCH:") and bundle_meta.exists():
            try:
                entries = json.loads(bundle_meta.read_text(encoding="utf-8"))
                files_dir = vault_path / "files"
                restored = 0
                for rel_str, orig_str in entries:
                    src_f = files_dir / rel_str
                    dst_f = Path(orig_str)
                    if src_f.exists() and not dst_f.exists():
                        self._move_fast(src_f, dst_f)
                        restored += 1
                shutil.rmtree(vault_path, ignore_errors=True)
                with self._lock:
                    cur = self._load_manifest()
                    self._save_manifest([r for r in cur if r["item_id"] != item_id])
                return True, f"Lote restaurado: {restored} archivos devueltos a su ubicacion original"
            except (OSError, json.JSONDecodeError) as exc:
                return False, f"Error restaurando lote: {exc}"

        original_path = Path(match["original_path"])
        if original_path.exists():
            return False, "Ya existe un archivo en la ruta original de destino"

        if not match.get("is_dir", False) and sha_tag not in ("DIRECTORY", "FAST_SKIP", ""):
            if compute_sha256(vault_path) != sha_tag:
                return False, "Fallo de integridad SHA-256 en boveda"

        self._move_fast(vault_path, original_path)
        with self._lock:
            cur = self._load_manifest()
            self._save_manifest([r for r in cur if r["item_id"] != item_id])
        return True, f"Restaurado en {original_path}"

    def purge_item(self, item_id: str, use_recycle_bin: bool = True) -> tuple[bool, str]:
        """Permanently purge or recycle an item from the Quarantine Vault."""
        res = self.purge_items([item_id], use_recycle_bin=use_recycle_bin)
        if res["purged"] == 0:
            return False, "Registro no encontrado"
        return True, "Elemento depurado de la boveda"

    def purge_items(
        self,
        item_ids: list[str],
        use_recycle_bin: bool = False,
        progress_cb: Callable[[int, str], None] | None = None,
    ) -> dict[str, int]:
        """Remove multiple Quarantine Vault entries efficiently in a single manifest save."""
        target_set = set(item_ids)
        with self._lock:
            records = self._load_manifest()
        targets = [r for r in records if r.get("item_id") in target_set]
        if not targets:
            return {"purged": 0, "freed_bytes": 0}

        purged_ids: set[str] = set()
        freed_bytes = 0
        total = max(1, len(targets))
        for idx, match in enumerate(targets, start=1):
            if progress_cb and (idx == 1 or idx % 100 == 0 or idx == total):
                pct = 10 + int(idx * 85 / total)
                progress_cb(pct, f"Depurando boveda ({idx}/{total})...")
            vault_path = Path(match["vault_path"])
            try:
                if vault_path.exists():
                    if use_recycle_bin and send_to_recycle_bin(vault_path):
                        pass
                    elif vault_path.is_dir():
                        shutil.rmtree(vault_path, ignore_errors=False)
                    else:
                        vault_path.unlink()
                purged_ids.add(str(match["item_id"]))
                freed_bytes += int(match.get("size_bytes") or 0)
            except OSError:
                continue

        if purged_ids:
            with self._lock:
                cur = self._load_manifest()
                self._save_manifest([r for r in cur if r.get("item_id") not in purged_ids])
        return {"purged": len(purged_ids), "freed_bytes": freed_bytes}


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
