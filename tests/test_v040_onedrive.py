"""Tests for WinOptiAI v0.4.0 OneDrive Hybrid (DPAPI, Files On-Demand, Cloud Graph)."""

from __future__ import annotations

import os
from pathlib import Path
import time

from winoptiai.core.safety_guard import PreOpBackupManager
from winoptiai.core.win32_bridge import dpapi_protect, dpapi_unprotect
from winoptiai.storage.onedrive_optimizer import (
    OneDriveRoot,
    OneDriveTokenStore,
    fetch_cloud_drive_quota,
    scan_cloud_onedrive,
    scan_local_onedrive_candidates,
    trash_cloud_onedrive_items,
)


def test_dpapi_and_token_store_encryption(tmp_path: Path) -> None:
    secret = b"refresh_token_super_secreto_12345"
    enc = dpapi_protect(secret)
    assert enc != secret
    assert dpapi_unprotect(enc) == secret

    store = OneDriveTokenStore(app_dir=tmp_path)
    store.save({"client_id": "abc-123", "access_token": "tok_secret_xyz", "authority": "common"})
    raw_disk = store.blob_path.read_bytes()
    assert b"tok_secret_xyz" not in raw_disk
    loaded = store.load()
    assert loaded["client_id"] == "abc-123"
    assert loaded["access_token"] == "tok_secret_xyz"


def test_local_onedrive_protects_git_and_detects_stale_files(tmp_path: Path) -> None:
    od_root = tmp_path / "OneDriveTest"
    od_root.mkdir()

    # Active Git repository must NEVER be proposed for dehydration
    repo = od_root / "MiProyecto"
    (repo / ".git").mkdir(parents=True)
    repo_big = repo / "weights.bin"
    repo_big.write_bytes(b"R" * (2 * 1024 * 1024))

    # Stale non-repo file should be proposed
    archive = od_root / "DocumentosViejos"
    archive.mkdir()
    stale_zip = archive / "respaldo_antiguo.zip"
    stale_zip.write_bytes(b"Z" * (2 * 1024 * 1024))
    old_ts = time.time() - (45 * 86400)
    os.utime(stale_zip, (old_ts, old_ts))
    os.utime(repo_big, (old_ts, old_ts))

    root = OneDriveRoot(label="TestOneDrive", path=od_root)
    cands = scan_local_onedrive_candidates(
        roots=[root],
        min_size_mb=1.0,
        min_inactive_days=30,
        protect_git_repos=True,
    )
    assert len(cands) == 1
    assert cands[0].local_path == stale_zip


def test_cloud_graph_duplicates_shared_guardrail_and_trash(tmp_path: Path) -> None:
    delta_page = {
        "value": [
            {
                "id": "keep1",
                "name": "informe.pdf",
                "size": 5_000_000,
                "file": {"hashes": {"quickXorHash": "HASH_SAME"}},
                "parentReference": {"path": "/drive/root:/Finanzas"},
                "lastModifiedDateTime": "2026-01-10T10:00:00Z",
                "webUrl": "https://onedrive.live.com/keep1",
            },
            {
                "id": "dup2",
                "name": "informe (copia).pdf",
                "size": 5_000_000,
                "file": {"hashes": {"quickXorHash": "HASH_SAME"}},
                "parentReference": {"path": "/drive/root:/Finanzas/Respaldos/2026"},
                "lastModifiedDateTime": "2026-02-15T10:00:00Z",
                "webUrl": "https://onedrive.live.com/dup2",
            },
            {
                # Third-party shared item must be excluded when allow_shared=False
                "id": "shared3",
                "name": "compartido.pdf",
                "size": 5_000_000,
                "file": {"hashes": {"quickXorHash": "HASH_SAME"}},
                "remoteItem": {"id": "rem999"},
                "parentReference": {"path": "/drive/root:/Compartidos"},
                "lastModifiedDateTime": "2026-03-01T10:00:00Z",
            },
        ]
    }

    def _fake_get(url: str, _tok: str) -> dict:
        if url.endswith("/me/drive"):
            return {
                "driveType": "business",
                "owner": {"user": {"displayName": "Dairo", "email": "dairo@org.example"}},
                "quota": {"total": 1000, "used": 400, "remaining": 600, "deleted": 10},
            }
        return delta_page

    quota = fetch_cloud_drive_quota("tok", graph_get_fn=_fake_get)
    assert quota.drive_type == "business"
    assert quota.used_bytes == 400

    pcts: list[int] = []
    dups = scan_cloud_onedrive(
        "tok",
        scan_kind="duplicates",
        allow_shared=False,
        progress_cb=lambda p, _s: pcts.append(p),
        graph_get_fn=_fake_get,
    )
    assert len(dups) == 1
    assert dups[0].item_id == "dup2"
    assert pcts[-1] == 100

    deleted_urls: list[str] = []
    backup = PreOpBackupManager(root_dir=tmp_path / "bkp")
    res = trash_cloud_onedrive_items(
        "tok",
        dups,
        backup_mgr=backup,
        graph_delete_fn=lambda url, _t: deleted_urls.append(url) or True,
    )
    assert res["trashed"] == 1
    assert any("dup2" in u for u in deleted_urls)
