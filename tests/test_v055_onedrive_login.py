"""WinOptiAI v0.5.5: redirect URI de OneDrive (AADSTS50011) y escrituras atomicas concurrentes."""

from __future__ import annotations

import json
from pathlib import Path
import threading
import urllib.parse
import urllib.request

from winoptiai.core.safety_guard import atomic_write_text
from winoptiai.storage import onedrive_optimizer as od


def test_oauth_redirect_uri_matches_plain_localhost_registration(tmp_path: Path, monkeypatch) -> None:
    sent: dict[str, str] = {}

    def _fake_browser(url: str) -> bool:
        q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
        sent["redirect_uri"] = q["redirect_uri"][0]
        back = q["redirect_uri"][0] + "/?" + urllib.parse.urlencode(
            {"state": q["state"][0], "error": "access_denied", "error_description": "prueba"}
        )
        threading.Thread(target=lambda: urllib.request.urlopen(back, timeout=5).read(), daemon=True).start()
        return True

    monkeypatch.setattr(od.webbrowser, "open", _fake_browser)
    store = od.OneDriveTokenStore(app_dir=tmp_path)
    ok, msg = od.start_oauth_pkce_login("1a9fbb52-0000-0000-0000-000000000000", store=store, timeout_sec=10)
    parsed = urllib.parse.urlparse(sent["redirect_uri"])
    # Entra ID ignora el puerto en http://localhost, pero compara la ruta: debe ir vacia.
    assert parsed.scheme == "http" and parsed.hostname == "localhost" and parsed.path in ("", "/")
    assert not ok and "prueba" in msg


def test_atomic_write_concurrent_writers_never_fail(tmp_path: Path) -> None:
    target = tmp_path / "notifications.json"
    errors: list[BaseException] = []

    def _writer(n: int) -> None:
        try:
            for i in range(40):
                atomic_write_text(target, json.dumps({"w": n, "i": i}))
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    threads = [threading.Thread(target=_writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert errors == []
    assert json.loads(target.read_text(encoding="utf-8"))["i"] == 39
    assert list(tmp_path.glob("*.tmp")) == []
