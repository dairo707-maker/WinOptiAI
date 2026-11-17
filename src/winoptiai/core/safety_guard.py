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
import stat
import time
from typing import Any, Callable
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
    "c:\\windows\\softwaredistribution\\download",
    "c:\\windows\\softwaredistribution\\deliveryoptimization",
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


def atomic_write_text(path: Path, text: str, retries: int = 5) -> None:
    """Atomically replace a local JSON/config file with retry backoff against AV locks."""
    path.parent.mkdir(parents=True, exist_ok=True)
    # v0.5.5: temporal unico por escritura. Con un nombre fijo (notifications.tmp), dos
    # escrituras simultaneas (p. ej. dos avisos de AI Boost) se pisaban y la segunda fallaba con
    # FileNotFoundError al renombrar (crash.log 16/11 22:45).
    tmp = path.with_name(f"{path.stem}.{os.getpid()}.{uuid.uuid4().hex[:8]}.tmp")
    tmp.write_text(text, encoding="utf-8")
    try:
        for attempt in range(retries):
            try:
                tmp.replace(path)
                return
            except PermissionError:
                if attempt == retries - 1:
                    raise
                time.sleep(0.06 * (attempt + 1))
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


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


ORPHAN_MIN_AGE_SEC = 15 * 60  # v0.5.4: no tocar carpetas de cuarentena recien creadas


def _long_path(path: Path | str) -> str:
    """Prefijo ``\\\\?\\`` en Windows para rutas de mas de 260 caracteres."""
    p = os.path.abspath(str(path))
    if os.name != "nt" or p.startswith("\\\\?\\"):
        return p
    if p.startswith("\\\\"):
        return "\\\\?\\UNC\\" + p[2:]
    return "\\\\?\\" + p


def _strip_long(p: str) -> str:
    return p[4:] if p.startswith("\\\\?\\") else p


def _force_unlink(path: Path) -> list[Path]:
    lp = _long_path(path)
    try:
        os.chmod(lp, stat.S_IWRITE)
    except OSError:
        pass
    try:
        os.unlink(lp)
        return []
    except FileNotFoundError:
        return []
    except OSError:
        return [path]


def force_remove_tree(path: Path, progress_cb: Callable[[int, str], None] | None = None) -> list[Path]:
    """Borrar un arbol de la boveda quitando atributos de solo lectura y usando rutas largas.

    Devuelve los archivos que siguieron bloqueados (vacio = borrado completo). Solo se usa
    dentro de la boveda de cuarentena, nunca sobre rutas del usuario.
    """
    blocked: list[Path] = []
    root = _long_path(path)
    count = 0
    for dirpath, dirnames, filenames in os.walk(root, topdown=False):
        for name in filenames:
            fp = os.path.join(dirpath, name)
            try:
                os.unlink(fp)
            except FileNotFoundError:
                pass
            except OSError:
                try:
                    os.chmod(fp, stat.S_IWRITE)
                    os.unlink(fp)
                except FileNotFoundError:
                    pass
                except OSError:
                    blocked.append(Path(_strip_long(fp)))
            count += 1
            if progress_cb and count % 2000 == 0:
                progress_cb(50, f"Eliminando archivos de la boveda ({count:,})...".replace(",", "."))
        for name in dirnames:
            dp = os.path.join(dirpath, name)
            try:
                os.rmdir(dp)
            except OSError:
                try:
                    os.chmod(dp, stat.S_IWRITE)
                    os.rmdir(dp)
                except OSError:
                    pass  # no vacio: contiene archivos bloqueados ya reportados
    try:
        os.rmdir(root)
    except FileNotFoundError:
        pass
    except OSError:
        try:
            os.chmod(root, stat.S_IWRITE)
            os.rmdir(root)
        except OSError:
            if not blocked and os.path.exists(root):
                blocked.append(path)
    return blocked


def _tree_size(path: Path) -> int:
    total = 0
    for dirpath, _dirs, files in os.walk(_long_path(path)):
        for name in files:
            try:
                total += os.lstat(os.path.join(dirpath, name)).st_size
            except OSError:
                pass
    return total


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
        atomic_write_text(
            self.manifest_path,
            json.dumps(records, indent=2, ensure_ascii=False),
        )

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
        controller: Any = None,
    ) -> dict[str, Any]:
        """Move disposable/temp files into ONE reversible batch bundle with cooperative pause/cancel."""
        if not sources:
            return {
                "moved": 0,
                "skipped": 0,
                "permission_denied": 0,
                "freed_bytes": 0,
                "interrupted": "",
                "remaining_sources": [],
            }

        if is_protected_path(base_dir, allow_system_temp=allow_system_temp):
            return {
                "moved": 0,
                "skipped": len(sources),
                "permission_denied": 0,
                "freed_bytes": 0,
                "interrupted": "",
                "remaining_sources": [],
            }

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
        interrupted = ""
        remaining_sources: list[tuple[Path, int]] = []

        for idx, (src, est_size) in enumerate(sources, start=1):
            if controller is not None and (idx == 1 or idx % 50 == 0):
                state = controller.checkpoint()
                if state in ("cancel", "save_pause"):
                    interrupted = state
                    remaining_sources = sources[idx - 1 :]
                    break
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
                "interrupted": interrupted,
                "remaining_sources": remaining_sources,
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
            "interrupted": interrupted,
            "remaining_sources": remaining_sources,
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
        if res["failed"]:
            return False, f"{res['blocked_files']} archivo(s) siguen bloqueados en la boveda"
        if res["purged"] == 0:
            return False, "Registro no encontrado"
        return True, "Elemento depurado de la boveda"

    def _manifest_is_readable(self) -> bool:
        """False si el manifiesto existe pero no se puede leer/parsear (fallar cerrado)."""
        if not self.manifest_path.exists():
            return True
        try:
            return isinstance(json.loads(self.manifest_path.read_text(encoding="utf-8")), list)
        except (OSError, json.JSONDecodeError):
            return False

    def list_orphan_entries(self, min_age_sec: float = ORPHAN_MIN_AGE_SEC) -> list[Path]:
        """Restos dentro de ``items/`` sin registro en el manifiesto (purgas interrumpidas).

        Falla cerrado: si el manifiesto no se puede leer no hay restos (nunca se trata la boveda
        entera como basura). Se ignoran entradas modificadas hace menos de ``min_age_sec``: una
        cuarentena en curso crea su carpeta antes de registrarla en el manifiesto.
        """
        now = time.time()
        out: list[Path] = []
        with self._lock:
            if not self._manifest_is_readable():
                return []
            records = self._load_manifest()
            known = {os.path.normcase(os.path.abspath(str(r.get("vault_path") or ""))) for r in records}
            try:
                for entry in os.scandir(self.items_dir):
                    if os.path.normcase(os.path.abspath(entry.path)) in known:
                        continue
                    try:
                        if now - entry.stat(follow_symlinks=False).st_mtime < min_age_sec:
                            continue
                    except OSError:
                        continue
                    out.append(Path(entry.path))
            except OSError:
                pass
        return out

    def purge_items(
        self,
        item_ids: list[str],
        use_recycle_bin: bool = False,
        progress_cb: Callable[[int, str], None] | None = None,
        include_orphans: bool = False,
        orphan_paths: list[Path] | None = None,
    ) -> dict[str, Any]:
        """Remove multiple Quarantine Vault entries efficiently in a single manifest save.

        v0.5.4: los archivos de solo lectura y las rutas largas (>260) ya no bloquean la purga en
        silencio. Si algo queda bloqueado (p. ej. abierto por otro programa), el registro se
        conserva con el tamano restante y se informa en ``failed`` / ``blocked_samples``.
        """
        target_set = set(item_ids)
        with self._lock:
            records = self._load_manifest()
        targets = [r for r in records if r.get("item_id") in target_set]
        orphans: list[Path] = []
        if include_orphans:
            # Solo los restos que el usuario confirmo y que siguen siendo restos ahora mismo.
            current = {os.path.normcase(str(p)) for p in self.list_orphan_entries()}
            candidates = orphan_paths if orphan_paths is not None else [Path(c) for c in current]
            orphans = [p for p in candidates if os.path.normcase(str(p)) in current]
        result: dict[str, Any] = {
            "purged": 0,
            "freed_bytes": 0,
            "failed": 0,
            "blocked_files": 0,
            "blocked_samples": [],
            "orphans_removed": 0,
        }
        if not targets and not orphans:
            return result

        purged_ids: set[str] = set()
        updated_sizes: dict[str, int] = {}
        total = max(1, len(targets) + len(orphans))
        for idx, match in enumerate(targets, start=1):
            if progress_cb:
                progress_cb(10 + int(idx * 85 / total), f"Depurando boveda ({idx}/{total})...")
            vault_path = Path(match["vault_path"])
            size_before = int(match.get("size_bytes") or 0)
            if vault_path.exists() and use_recycle_bin and send_to_recycle_bin(vault_path):
                pass
            elif vault_path.exists():
                blocked = force_remove_tree(vault_path, progress_cb=progress_cb)
                if blocked:
                    remaining = _tree_size(vault_path)
                    updated_sizes[str(match["item_id"])] = remaining
                    result["failed"] += 1
                    result["blocked_files"] += len(blocked)
                    result["blocked_samples"].extend(str(p) for p in blocked[:5])
                    result["freed_bytes"] += max(0, size_before - remaining)
                    continue
            purged_ids.add(str(match["item_id"]))
            result["freed_bytes"] += size_before

        for orphan in orphans:
            blocked = force_remove_tree(orphan) if orphan.is_dir() else _force_unlink(orphan)
            if not blocked:
                result["orphans_removed"] += 1
            else:
                result["blocked_files"] += len(blocked)
                result["blocked_samples"].extend(str(p) for p in blocked[:5])

        if purged_ids or updated_sizes:
            with self._lock:
                cur = self._load_manifest()
                kept = []
                for r in cur:
                    rid = str(r.get("item_id"))
                    if rid in purged_ids:
                        continue
                    if rid in updated_sizes:
                        r = dict(r, size_bytes=updated_sizes[rid])
                    kept.append(r)
                self._save_manifest(kept)
        result["purged"] = len(purged_ids)
        result["blocked_samples"] = result["blocked_samples"][:10]
        return result

    def purge_expired_items(
        self,
        max_age_days: int = 30,
        only_junk_categories: bool = True,
    ) -> dict[str, int]:
        """Auto-purge old temporary Quarantine bundles beyond retention days to keep C: healthy."""
        cutoff_ts = time.time() - (max(1, max_age_days) * 86400)
        with self._lock:
            records = self._load_manifest()
        expired_ids: list[str] = []
        for rec in records:
            if only_junk_categories and not str(rec.get("category") or "").startswith("Basura:"):
                continue
            raw_ts = str(rec.get("quarantined_at") or "")
            try:
                dt = datetime.fromisoformat(raw_ts)
                if dt.timestamp() <= cutoff_ts:
                    expired_ids.append(str(rec["item_id"]))
            except ValueError:
                continue
        if not expired_ids:
            return {"purged": 0, "freed_bytes": 0}
        return self.purge_items(expired_ids, use_recycle_bin=False)


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
