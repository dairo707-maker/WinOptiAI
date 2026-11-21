"""Hybrid OneDrive Local (Files On-Demand) + Cloud (Microsoft Graph PKCE) optimizer.

Capabilities:
1. Local Files On-Demand dehydration: converts inactive/heavy hydrated OneDrive files
   into 'Online-only' placeholders via Win32 SetFileAttributesW (+U -P), freeing local
   SSD space without deleting any files from OneDrive cloud and automatically protecting
   active Git repositories (.git / .venv / node_modules).
2. Cloud OneDrive optimization (Microsoft Graph OAuth 2.0 PKCE + Windows DPAPI vault):
   - Enumerates cloud drive quota and delta items without downloading file contents
   - Detects exact cloud duplicates via native quickXorHash / sha256Hash
   - Detects heavy cloud files while excluding third-party shared items by default
   - Safely moves selected redundant cloud files into the OneDrive Recycle Bin
"""

from __future__ import annotations

import base64
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
import hashlib
from http.server import BaseHTTPRequestHandler, HTTPServer
import json
import os
from pathlib import Path
import secrets
import threading
import time
from typing import Any, Callable
import urllib.error
import urllib.parse
import urllib.request
import webbrowser

from ..core.safety_guard import PreOpBackupManager, default_app_data_dir, is_protected_path
from ..core.task_control import TaskCanceledError, TaskController, stop_point
from ..core.usage_telemetry import file_last_used_ts, parse_iso_timestamp
from ..core.win32_bridge import (
    IS_WINDOWS,
    attrs_is_cloud_only,
    attrs_is_reparse_or_system,
    dehydrate_onedrive_file,
    dpapi_protect,
    dpapi_unprotect,
    get_locking_processes,
)


EXCLUDED_DEV_DIRS: frozenset[str] = frozenset(
    {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
    }
)
GRAPH_BASE = "https://graph.microsoft.com/v1.0"
DEFAULT_SCOPES = "User.Read Files.ReadWrite offline_access"


@dataclass(slots=True)
class OneDriveRoot:
    """Detected local synced OneDrive root folder."""

    label: str
    path: Path
    email: str = ""
    is_business: bool = False


@dataclass(slots=True)
class OneDriveCandidate:
    """Unified local-hydrated or cloud OneDrive optimization candidate."""

    item_id: str
    scope: str          # "LOCAL_HYDRATED" | "CLOUD_DUPLICATE" | "CLOUD_HEAVY"
    name: str
    location: str
    size_bytes: int
    last_modified: str
    reason: str
    local_path: Path | None = None
    web_url: str = ""
    cloud_hash: str = ""
    group_key: str = ""
    last_used_ts: float = 0.0


@dataclass(slots=True)
class OneDriveQuota:
    """Microsoft Graph OneDrive storage quota summary."""

    owner_name: str
    owner_email: str
    drive_type: str
    total_bytes: int
    used_bytes: int
    remaining_bytes: int
    deleted_bytes: int


def discover_onedrive_roots() -> list[OneDriveRoot]:
    """Discover active personal and commercial OneDrive sync folders on Windows."""
    found: dict[str, OneDriveRoot] = {}

    if IS_WINDOWS:
        import winreg

        base_key = r"Software\Microsoft\OneDrive\Accounts"
        try:
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, base_key) as root_k:
                sub_count = winreg.QueryInfoKey(root_k)[0]
                for idx in range(sub_count):
                    try:
                        sub_name = winreg.EnumKey(root_k, idx)
                        with winreg.OpenKey(root_k, sub_name) as acc_k:
                            folder = ""
                            email = ""
                            display = sub_name
                            is_biz = "business" in sub_name.lower()
                            for val_name in ("UserFolder", "UserEmail", "DisplayName"):
                                try:
                                    val, _ = winreg.QueryValueEx(acc_k, val_name)
                                except OSError:
                                    continue
                                if val_name == "UserFolder" and isinstance(val, str):
                                    folder = val
                                elif val_name == "UserEmail" and isinstance(val, str):
                                    email = val
                                elif val_name == "DisplayName" and isinstance(val, str) and val:
                                    display = val
                            if folder:
                                p = Path(folder)
                                if p.exists():
                                    key = str(p.resolve()).lower()
                                    found[key] = OneDriveRoot(
                                        label=display or p.name,
                                        path=p,
                                        email=email,
                                        is_business=is_biz,
                                    )
                    except OSError:
                        continue
        except OSError:
            pass

    for env_name, is_biz in (
        ("OneDriveCommercial", True),
        ("OneDriveConsumer", False),
        ("OneDrive", False),
    ):
        raw = os.environ.get(env_name)
        if not raw:
            continue
        p = Path(raw)
        if p.exists():
            key = str(p.resolve()).lower()
            if key not in found:
                found[key] = OneDriveRoot(label=p.name, path=p, is_business=is_biz)

    return list(found.values())


def scan_local_onedrive_candidates(
    roots: list[OneDriveRoot] | None = None,
    min_size_mb: float = 25.0,
    min_inactive_days: int = 30,
    protect_git_repos: bool = True,
    progress_cb: Callable[[int, str], None] | None = None,
    controller: TaskController | None = None,
) -> list[OneDriveCandidate]:
    """Find locally hydrated OneDrive files eligible for Files On-Demand dehydration."""
    target_roots = roots if roots is not None else discover_onedrive_roots()
    if not target_roots:
        return []

    now_ts = time.time()
    cutoff_ts = now_ts - (max(0, min_inactive_days) * 86400)
    min_bytes = max(1, int(min_size_mb * 1024 * 1024))
    candidates: list[OneDriveCandidate] = []
    total_roots = max(1, len(target_roots))

    for r_idx, root in enumerate(target_roots):
        if progress_cb:
            progress_cb(
                5 + int(r_idx * 85 / total_roots),
                f"Escaneando OneDrive local ({root.label})...",
            )
        if not root.path.exists() or is_protected_path(root.path):
            continue

        stack: list[Path] = [root.path]
        visited_dirs = 0
        while stack:
            stop_point(controller, "Escaneo de OneDrive cancelado por el usuario")
            cur = stack.pop()
            if is_protected_path(cur):
                continue
            try:
                with os.scandir(cur) as it:
                    entries = list(it)
            except OSError:
                continue

            if protect_git_repos and any(
                e.name in {".git", ".venv"} and e.is_dir(follow_symlinks=False) for e in entries
            ):
                # Never dehydrate files inside active Git/Python development workspaces
                continue

            visited_dirs += 1
            if progress_cb and visited_dirs % 80 == 0:
                pct = min(92, 10 + int((r_idx * 80 / total_roots)) + min(70, visited_dirs // 40))
                progress_cb(pct, f"Inspeccionando {cur.name}...")

            for entry in entries:
                ep = Path(entry.path)
                try:
                    st = entry.stat(follow_symlinks=False)
                except OSError:
                    continue
                attrs = getattr(st, "st_file_attributes", None)
                if entry.is_dir(follow_symlinks=False):
                    if entry.name in EXCLUDED_DEV_DIRS or attrs_is_reparse_or_system(attrs):
                        continue
                    stack.append(ep)
                elif entry.is_file(follow_symlinks=False):
                    if attrs_is_cloud_only(attrs) or attrs_is_reparse_or_system(attrs):
                        continue
                    size = int(st.st_size)
                    if size < min_bytes:
                        continue
                    # Use mtime rather than atime because AV/Windows Search/OneDrive sync touch atime
                    last_touch = st.st_mtime
                    if last_touch > cutoff_ts:
                        continue
                    days_idle = max(0, int((now_ts - last_touch) / 86400))
                    candidates.append(
                        OneDriveCandidate(
                            item_id=str(ep),
                            scope="LOCAL_HYDRATED",
                            name=entry.name,
                            location=str(ep),
                            size_bytes=size,
                            last_modified=datetime.fromtimestamp(st.st_mtime).strftime("%Y-%m-%d"),
                            reason=f"En disco ({days_idle}d sin uso)",
                            local_path=ep,
                            last_used_ts=file_last_used_ts(st),
                        )
                    )

    candidates.sort(key=lambda c: c.size_bytes, reverse=True)
    if progress_cb:
        progress_cb(100, f"OneDrive local analizado ({len(candidates)} elegibles)")
    return candidates


def dehydrate_local_onedrive_files(
    candidates: list[OneDriveCandidate],
    backup_mgr: PreOpBackupManager | None = None,
    progress_cb: Callable[[int, str], None] | None = None,
) -> dict[str, int]:
    """Convert selected hydrated OneDrive files into Online-only placeholders (+U -P)."""
    targets = [c for c in candidates if c.local_path and c.local_path.exists()]
    if not targets:
        return {"dehydrated": 0, "skipped": 0, "freed_bytes": 0}

    if backup_mgr is not None:
        backup_mgr.create_operation_snapshot(
            "onedrive_deshidratar_local",
            [{"path": str(c.local_path), "size_bytes": c.size_bytes} for c in targets],
        )

    dehydrated = 0
    skipped = 0
    freed = 0
    total = max(1, len(targets))

    for idx, item in enumerate(targets, start=1):
        if progress_cb and (idx == 1 or idx % 10 == 0 or idx == total):
            progress_cb(10 + int(idx * 85 / total), f"Liberando espacio local ({idx}/{total})...")
        assert item.local_path is not None
        if get_locking_processes([item.local_path]):
            skipped += 1
            continue
        ok, _ = dehydrate_onedrive_file(item.local_path)
        if ok:
            dehydrated += 1
            freed += item.size_bytes
        else:
            skipped += 1

    if progress_cb:
        progress_cb(100, "Archivos marcados como Solo en la nube")
    return {"dehydrated": dehydrated, "skipped": skipped, "freed_bytes": freed}


class OneDriveTokenStore:
    """Stores Microsoft Graph OAuth configuration & tokens encrypted via Windows DPAPI."""

    def __init__(self, app_dir: Path | None = None) -> None:
        self.base_dir = app_dir or default_app_data_dir()
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.blob_path = self.base_dir / "onedrive_auth.dpapi"

    def save(self, data: dict[str, Any]) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        encrypted = dpapi_protect(raw)
        tmp = self.blob_path.with_suffix(".tmp")
        tmp.write_bytes(encrypted)
        tmp.replace(self.blob_path)

    def load(self) -> dict[str, Any]:
        if not self.blob_path.exists():
            return {}
        try:
            decrypted = dpapi_unprotect(self.blob_path.read_bytes())
            data = json.loads(decrypted.decode("utf-8"))
            return data if isinstance(data, dict) else {}
        except (OSError, ValueError, json.JSONDecodeError):
            return {}

    def clear_tokens(self) -> None:
        cur = self.load()
        kept = {
            "client_id": cur.get("client_id", ""),
            "authority": cur.get("authority", "common"),
        }
        if kept["client_id"]:
            self.save(kept)
        elif self.blob_path.exists():
            self.blob_path.unlink(missing_ok=True)


def _pkce_pair() -> tuple[str, str]:
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(48)).decode("ascii").rstrip("=")
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).decode("ascii").rstrip("=")
    return verifier, challenge


def _http_form_post(url: str, form: dict[str, str], timeout: int = 20) -> dict[str, Any]:
    encoded = urllib.parse.urlencode(form).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=encoded,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _default_graph_get(url: str, access_token: str, timeout: int = 25) -> dict[str, Any]:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}", "Accept": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _default_graph_delete(url: str, access_token: str, timeout: int = 20) -> bool:
    req = urllib.request.Request(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        method="DELETE",
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return 200 <= resp.status < 300
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            return False
        raise


def start_oauth_pkce_login(
    client_id: str,
    authority: str = "common",
    store: OneDriveTokenStore | None = None,
    timeout_sec: int = 120,
    progress_cb: Callable[[int, str], None] | None = None,
) -> tuple[bool, str]:
    """Authenticate OneDrive Personal or Entra ID via local OAuth 2.0 PKCE + DPAPI storage."""
    cid = client_id.strip()
    if not cid:
        return False, "Configure primero un Application (Client) ID de Azure Entra ID."

    auth_tenant = authority.strip() or "common"
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(24)
    result_box: dict[str, str] = {}
    done_evt = threading.Event()

    class _CallbackHandler(BaseHTTPRequestHandler):
        def log_message(self, _format: str, *_args: Any) -> None:
            return

        def do_GET(self) -> None:  # noqa: N802
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if params.get("state", [""])[0] != state:
                self.send_response(400)
                self.end_headers()
                self.wfile.write(b"Estado OAuth invalido.")
                return
            if "error" in params:
                result_box["error"] = params.get("error_description", params["error"])[0]
            elif "code" in params:
                result_box["code"] = params["code"][0]
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(
                b"<html><body style='font-family:sans-serif;padding:24px'>"
                b"<h2>WinOptiAI - Autenticacion completada</h2>"
                b"<p>Ya puedes cerrar esta pestana y regresar a WinOptiAI.</p>"
                b"</body></html>"
            )
            done_evt.set()

    server = HTTPServer(("127.0.0.1", 0), _CallbackHandler)
    port = server.server_address[1]
    # v0.5.5: sin ruta "/callback". Entra ID ignora el puerto en http://localhost para apps de
    # escritorio, pero SI compara la ruta: con "/callback" el registro "http://localhost" daba
    # AADSTS50011. El servidor local acepta la respuesta en cualquier ruta (valida "state").
    redirect_uri = f"http://localhost:{port}"

    serve_thread = threading.Thread(target=server.serve_forever, daemon=True)
    serve_thread.start()

    try:
        auth_query = urllib.parse.urlencode(
            {
                "client_id": cid,
                "response_type": "code",
                "redirect_uri": redirect_uri,
                "response_mode": "query",
                "scope": DEFAULT_SCOPES,
                "state": state,
                "code_challenge": challenge,
                "code_challenge_method": "S256",
                "prompt": "select_account",
            }
        )
        auth_url = f"https://login.microsoftonline.com/{auth_tenant}/oauth2/v2.0/authorize?{auth_query}"
        if progress_cb:
            progress_cb(20, "Esperando autorizacion en el navegador...")
        webbrowser.open(auth_url)

        if not done_evt.wait(timeout=timeout_sec):
            return False, "Tiempo agotado esperando inicio de sesion de Microsoft."
    finally:
        server.shutdown()
        server.server_close()

    if "error" in result_box:
        return False, f"Acceso rechazado o bloqueado por el tenant: {result_box['error']}"

    code = result_box.get("code", "")
    if not code:
        return False, "No se recibio codigo de autorizacion OAuth."

    if progress_cb:
        progress_cb(65, "Intercambiando token PKCE cifrado con DPAPI...")

    token_url = f"https://login.microsoftonline.com/{auth_tenant}/oauth2/v2.0/token"
    try:
        tok = _http_form_post(
            token_url,
            {
                "client_id": cid,
                "grant_type": "authorization_code",
                "code": code,
                "redirect_uri": redirect_uri,
                "code_verifier": verifier,
                "scope": DEFAULT_SCOPES,
            },
        )
    except (urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        return False, f"Error obteniendo token Microsoft Graph: {exc}"

    access_token = str(tok.get("access_token") or "")
    if not access_token:
        return False, "Microsoft no devolvio access_token."

    owner_name = ""
    owner_email = ""
    try:
        me = _default_graph_get(f"{GRAPH_BASE}/me", access_token)
        owner_name = str(me.get("displayName") or "")
        owner_email = str(me.get("mail") or me.get("userPrincipalName") or "")
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        pass

    tok_store = store or OneDriveTokenStore()
    tok_store.save(
        {
            "client_id": cid,
            "authority": auth_tenant,
            "access_token": access_token,
            "refresh_token": str(tok.get("refresh_token") or ""),
            "expires_at": time.time() + int(tok.get("expires_in") or 3600) - 90,
            "owner_name": owner_name,
            "owner_email": owner_email,
        }
    )
    if progress_cb:
        progress_cb(100, "OneDrive conectado de forma segura")
    label = owner_email or owner_name or "Cuenta Microsoft"
    return True, f"Conectado a OneDrive Nube ({label}) con almacenamiento cifrado DPAPI."


def ensure_valid_access_token(store: OneDriveTokenStore | None = None) -> tuple[bool, str, dict[str, Any]]:
    """Return a valid Graph access token, refreshing automatically when needed."""
    tok_store = store or OneDriveTokenStore()
    data = tok_store.load()
    access = str(data.get("access_token") or "")
    refresh = str(data.get("refresh_token") or "")
    exp = float(data.get("expires_at") or 0.0)
    if access and time.time() < exp:
        return True, access, data

    if not refresh or not data.get("client_id"):
        return False, "", data

    authority = str(data.get("authority") or "common")
    token_url = f"https://login.microsoftonline.com/{authority}/oauth2/v2.0/token"
    try:
        tok = _http_form_post(
            token_url,
            {
                "client_id": str(data["client_id"]),
                "grant_type": "refresh_token",
                "refresh_token": refresh,
                "scope": DEFAULT_SCOPES,
            },
        )
    except (urllib.error.URLError, OSError, json.JSONDecodeError):
        return False, "", data

    new_access = str(tok.get("access_token") or "")
    if not new_access:
        return False, "", data

    data["access_token"] = new_access
    if tok.get("refresh_token"):
        data["refresh_token"] = str(tok["refresh_token"])
    data["expires_at"] = time.time() + int(tok.get("expires_in") or 3600) - 90
    tok_store.save(data)
    return True, new_access, data


def fetch_cloud_drive_quota(
    access_token: str,
    owner_hint: tuple[str, str] = ("", ""),
    graph_get_fn: Callable[[str, str], dict[str, Any]] | None = None,
) -> OneDriveQuota:
    """Fetch OneDrive cloud storage quota details via Microsoft Graph."""
    fetcher = graph_get_fn or _default_graph_get
    drv = fetcher(f"{GRAPH_BASE}/me/drive", access_token)
    quota = drv.get("quota") or {}
    owner = (drv.get("owner") or {}).get("user") or {}
    return OneDriveQuota(
        owner_name=str(owner.get("displayName") or owner_hint[0] or "OneDrive"),
        owner_email=str(owner.get("email") or owner_hint[1] or ""),
        drive_type=str(drv.get("driveType") or "onedrive"),
        total_bytes=int(quota.get("total") or 0),
        used_bytes=int(quota.get("used") or 0),
        remaining_bytes=int(quota.get("remaining") or 0),
        deleted_bytes=int(quota.get("deleted") or 0),
    )


def _format_graph_iso_date(raw: str) -> str:
    if not raw:
        return ""
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone()
        return dt.strftime("%Y-%m-%d")
    except ValueError:
        return raw[:10]


def scan_cloud_onedrive(
    access_token: str,
    scan_kind: str = "duplicates",
    min_heavy_mb: float = 25.0,
    allow_shared: bool = False,
    max_pages: int = 80,
    progress_cb: Callable[[int, str], None] | None = None,
    graph_get_fn: Callable[[str, str], dict[str, Any]] | None = None,
) -> list[OneDriveCandidate]:
    """Scan cloud OneDrive via /me/drive/root/delta using native hashes without downloading files."""
    fetcher = graph_get_fn or _default_graph_get
    next_url: str | None = (
        f"{GRAPH_BASE}/me/drive/root/delta"
        "?$select=id,name,size,file,folder,deleted,remoteItem,parentReference,webUrl,lastModifiedDateTime"
    )
    pages = 0
    raw_files: list[dict[str, Any]] = []

    while next_url and pages < max_pages:
        pages += 1
        if progress_cb:
            progress_cb(min(70, 8 + pages * 4), f"Consultando indice en la nube (pagina {pages})...")
        payload = fetcher(next_url, access_token)
        for item in payload.get("value") or []:
            if item.get("deleted") is not None:
                continue
            if not allow_shared and item.get("remoteItem") is not None:
                # Guardrail: never touch third-party shared folders by default
                continue
            if item.get("file") is None:
                continue
            raw_files.append(item)
        next_url = payload.get("@odata.nextLink")

    results: list[OneDriveCandidate] = []
    if scan_kind == "heavy":
        min_bytes = max(1, int(min_heavy_mb * 1024 * 1024))
        for item in raw_files:
            size = int(item.get("size") or 0)
            if size < min_bytes:
                continue
            parent_path = str((item.get("parentReference") or {}).get("path") or "").replace("/drive/root:", "OneDrive:")
            raw_dt = str(item.get("lastModifiedDateTime") or "")
            results.append(
                OneDriveCandidate(
                    item_id=str(item.get("id") or ""),
                    scope="CLOUD_HEAVY",
                    name=str(item.get("name") or ""),
                    location=f"{parent_path}/{item.get('name', '')}".strip("/"),
                    size_bytes=size,
                    last_modified=_format_graph_iso_date(raw_dt),
                    reason="Archivo pesado en la nube",
                    web_url=str(item.get("webUrl") or ""),
                    last_used_ts=parse_iso_timestamp(raw_dt),
                )
            )
        results.sort(key=lambda c: c.size_bytes, reverse=True)
    else:
        buckets: dict[tuple[int, str], list[dict[str, Any]]] = defaultdict(list)
        for item in raw_files:
            size = int(item.get("size") or 0)
            if size < 1024:
                continue
            hashes = (item.get("file") or {}).get("hashes") or {}
            digest = str(hashes.get("quickXorHash") or hashes.get("sha256Hash") or "")
            if not digest:
                continue
            buckets[(size, digest)].append(item)

        for (size, digest), group in buckets.items():
            if len(group) < 2:
                continue
            # Keep shortest path (or oldest modified) as primary; mark redundant copies
            ordered = sorted(
                group,
                key=lambda it: (
                    len(str((it.get("parentReference") or {}).get("path") or "")),
                    str(it.get("lastModifiedDateTime") or ""),
                ),
            )
            keep_name = str(ordered[0].get("name") or "")
            for dup in ordered[1:]:
                parent_path = str((dup.get("parentReference") or {}).get("path") or "").replace(
                    "/drive/root:", "OneDrive:"
                )
                raw_dt = str(dup.get("lastModifiedDateTime") or "")
                results.append(
                    OneDriveCandidate(
                        item_id=str(dup.get("id") or ""),
                        scope="CLOUD_DUPLICATE",
                        name=str(dup.get("name") or ""),
                        location=f"{parent_path}/{dup.get('name', '')}".strip("/"),
                        size_bytes=size,
                        last_modified=_format_graph_iso_date(raw_dt),
                        reason=f"Duplicado exacto de '{keep_name}'",
                        web_url=str(dup.get("webUrl") or ""),
                        cloud_hash=digest,
                        group_key=f"{size}:{digest[:10]}",
                        last_used_ts=parse_iso_timestamp(raw_dt),
                    )
                )
        results.sort(key=lambda c: c.size_bytes, reverse=True)

    if progress_cb:
        progress_cb(100, f"Escaneo en la nube completado ({len(results)} hallazgos)")
    return results


def trash_cloud_onedrive_items(
    access_token: str,
    candidates: list[OneDriveCandidate],
    backup_mgr: PreOpBackupManager | None = None,
    progress_cb: Callable[[int, str], None] | None = None,
    graph_delete_fn: Callable[[str, str], bool] | None = None,
) -> dict[str, int]:
    """Move selected cloud items to the OneDrive Recycle Bin (reversible) via Graph DELETE."""
    cloud_items = [c for c in candidates if c.scope in ("CLOUD_DUPLICATE", "CLOUD_HEAVY") and c.item_id]
    if not cloud_items:
        return {"trashed": 0, "skipped": 0, "freed_bytes": 0}

    if backup_mgr is not None:
        backup_mgr.create_operation_snapshot(
            "onedrive_papelera_nube",
            [
                {
                    "item_id": c.item_id,
                    "location": c.location,
                    "size_bytes": c.size_bytes,
                    "hash": c.cloud_hash,
                    "web_url": c.web_url,
                }
                for c in cloud_items
            ],
        )

    deleter = graph_delete_fn or _default_graph_delete
    trashed = 0
    skipped = 0
    freed = 0
    total = max(1, len(cloud_items))

    for idx, item in enumerate(cloud_items, start=1):
        if progress_cb:
            progress_cb(10 + int(idx * 85 / total), f"Enviando a Papelera OneDrive ({idx}/{total})...")
        try:
            url = f"{GRAPH_BASE}/me/drive/items/{urllib.parse.quote(item.item_id)}"
            if deleter(url, access_token):
                trashed += 1
                freed += item.size_bytes
            else:
                skipped += 1
        except (urllib.error.URLError, OSError):
            skipped += 1

    if progress_cb:
        progress_cb(100, "Elementos movidos a Papelera de OneDrive")
    return {"trashed": trashed, "skipped": skipped, "freed_bytes": freed}
