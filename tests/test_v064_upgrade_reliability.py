"""v0.6.4: actualizaciones sin cortes por tiempo, protegidas al cerrar la app y con fase visible."""

from __future__ import annotations

import os
import sys

from winoptiai.apps import app_manager
from winoptiai.apps.app_manager import (
    InstalledApp,
    interpret_winget_result,
    running_app_processes,
    upgrade_app_winget,
    winget_phase,
)
from winoptiai.core import win32_bridge
from winoptiai.core.safety_guard import is_protected_path
from winoptiai.core.task_control import TaskController


class _FakeProc:
    """Simula winget: escribe su salida en el archivo y termina tras `polls_until_done` consultas."""

    instances: list["_FakeProc"] = []

    def __init__(self, cmd, stdout=None, polls_until_done: int | None = 3, rc: int = 0, text: bytes = b"", **_kw):
        self.cmd = cmd
        self.pid = 4_000_000 + len(_FakeProc.instances)
        self._left = polls_until_done
        self._rc = rc
        self.killed = False
        if stdout is not None:
            stdout.write(text)
            stdout.flush()
        _FakeProc.instances.append(self)

    def poll(self):
        if self._left is None:
            return None
        self._left -= 1
        return self._rc if self._left <= 0 else None

    def kill(self):
        self.killed = True

    terminate = kill


def _app() -> InstalledApp:
    return InstalledApp(app_id="a", name="Antigravity IDE", version="2.7.0", available_version="2.8.0",
                        winget_id="Google.AntigravityIDE")


def _factory(**kw):
    def make(cmd, **popen_kw):
        return _FakeProc(cmd, **popen_kw, **kw)

    return make


def test_success_reports_phases_and_protects_pid(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    out = b"Downloading https://x/AntigravityIDE-installer.exe\r\nStarting package install...\r\nSuccessfully installed\r\n"
    msgs: list[str] = []
    ok, msg = upgrade_app_winget(
        _app(), progress_cb=lambda p, m: msgs.append(m), poll_s=0.001, popen=_factory(text=out, polls_until_done=4)
    )
    assert ok and "2.8.0" in msg
    proc = _FakeProc.instances[-1]
    assert proc.pid in win32_bridge._PROTECTED_CHILD_PIDS  # sobrevive al cierre total de la app
    assert "--silent" in proc.cmd and "Google.AntigravityIDE" in proc.cmd
    assert any("instalando" in m for m in msgs)
    assert (tmp_path / "WinOptiAI" / "logs" / "winget-upgrade-Google.AntigravityIDE.log").exists()


def test_slow_installer_is_never_killed(tmp_path, monkeypatch):
    """Caso real 21/11: winget se mataba a los 240 s con el instalador de Antigravity a medias."""
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ok, msg = upgrade_app_winget(
        _app(), timeout=0.05, poll_s=0.005, popen=_factory(polls_until_done=None, text=b"Starting package install...")
    )
    assert not ok and "segundo plano" in msg
    assert not _FakeProc.instances[-1].killed


def test_cancel_stops_waiting_without_killing(tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    ctl = TaskController("t")
    ctl.cancel()
    ok, msg = upgrade_app_winget(_app(), controller=ctl, poll_s=0.001, popen=_factory(polls_until_done=None))
    assert not ok and "segundo plano" in msg
    assert not _FakeProc.instances[-1].killed


def test_default_timeout_is_long():
    assert app_manager.WINGET_UPGRADE_MAX_WAIT_S >= 30 * 60


def test_interpret_winget_result_codes():
    assert interpret_winget_result(0, "") == (True, "ok")
    # 0x8A15002B sin signo y con signo (asi lo devuelve a veces Windows)
    assert interpret_winget_result(0x8A15002B, "") == (True, "al_dia")
    assert interpret_winget_result(0x8A15002B - 2**32, "") == (True, "al_dia")
    assert interpret_winget_result(1, "No se encontró ninguna actualización aplicable.")[1] == "al_dia"
    ok, why = interpret_winget_result(0x8A150011, "Error\r\nEl hash del instalador no coincide\r\n")
    assert not ok and "0x8A150011" in why and "hash" in why


def test_winget_phase_ignores_installer_word_in_urls():
    assert winget_phase("Descargando https://dl.google.com/AntigravityIDE-installer.exe\r  ████ 40%") == "descargando"
    assert winget_phase("Descargando ...\nIniciando la instalación del paquete...") == "instalando"
    assert winget_phase("") == ""


def test_winget_direct_download_setting(tmp_path):
    import json

    from winoptiai.apps.app_manager import ensure_winget_direct_download

    # winget sin instalar para el usuario: no se crea nada
    assert ensure_winget_direct_download(tmp_path / "noexiste" / "settings.json").startswith("omitido")
    # Archivo inexistente con carpeta de winget: se crea con WinINet
    p = tmp_path / "settings.json"
    assert ensure_winget_direct_download(p) == "aplicado"
    assert json.loads(p.read_text(encoding="utf-8"))["network"]["downloader"] == "wininet"
    assert ensure_winget_direct_download(p) == "ok"
    # Archivo propio con comentarios de linea y otras opciones: se conservan y se respalda
    p.write_text('// mis ajustes\n{\n  "visual": {"progressBar": "rainbow"},\n  "network": {"downloader": "do"}\n}\n', encoding="utf-8")
    assert ensure_winget_direct_download(p) == "aplicado"
    data = json.loads(p.read_text(encoding="utf-8"))
    assert data["visual"]["progressBar"] == "rainbow" and data["network"]["downloader"] == "wininet"
    assert (tmp_path / "settings.json.winoptiai.bak").exists()
    # Formato ilegible (comentario al final de linea): no se toca
    bad = '{"network": {"downloader": "do"} // nota\n}'
    p.write_text(bad, encoding="utf-8")
    assert ensure_winget_direct_download(p).startswith("omitido")
    assert p.read_text(encoding="utf-8") == bad


def test_ai_boost_never_touches_installers():
    from winoptiai.ai_optimizer.process_manager import is_installer_process_name

    for name in ("Antigravity%20IDE.tmp", "winget.exe", "msiexec.exe", "ZoomInstaller.exe", "Setup.exe", "unins000.exe"):
        assert is_installer_process_name(name), name
    for name in ("chrome.exe", "explorer.exe", "Antigravity.exe", ""):
        assert not is_installer_process_name(name), name


def test_running_app_processes_detects_open_app(tmp_path):
    folder = os.path.dirname(sys.executable)
    app = InstalledApp(app_id="py", name="Python", version="1", install_location=folder)
    found = running_app_processes(app)
    if not is_protected_path(folder.lower()):
        assert any(n.lower().startswith("python") for n in found)
    # Sin carpeta o carpeta inexistente: nada abierto
    assert running_app_processes(InstalledApp(app_id="x", name="X", version="1")) == []
    assert running_app_processes(InstalledApp(app_id="y", name="Y", version="1", install_location=str(tmp_path / "nada"))) == []
