"""v0.6.6: listado de Aplicaciones siempre al dia y fallos de actualizacion con motivo claro."""

from __future__ import annotations

import os
import time

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from winoptiai.apps.app_manager import InstalledApp, installer_blocking_processes  # noqa: E402


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


def _git_installer_log(path) -> None:
    path.write_text(
        "2026-11-22 14:10:08.293   Administrative install mode: Yes\n"
        "Setup has detected that the following processes are using Git:\n"
        "                          bash.exe (PID 7304)\n"
        "                          git.exe (PID 7310)\n"
        "                          bash.exe (PID 7311)\n"
        "                          \n"
        "                          Please terminate those processes and retry.\n"
        "2026-11-22 14:10:09.791   Failed to proceed to next wizard page; aborting.\n",
        encoding="utf-8",
    )


def test_blocking_processes_from_real_style_winget_output(tmp_path):
    log = tmp_path / "Git.Git.2.56.1.log"
    _git_installer_log(log)
    out_es = (
        "Iniciando instalación de paquete...\r\nError del instalador con el código de salida: 1\r\n"
        f"El registro del instalador está disponible en: {log}\r\n"
    )
    assert installer_blocking_processes(out_es) == ["bash.exe", "git.exe"]
    out_en = f"Installer failed with exit code: 1\nInstaller log is available at: {log}\n"
    assert installer_blocking_processes(out_en) == ["bash.exe", "git.exe"]
    # Sin registro, registro inexistente o ruta de red: nada
    assert installer_blocking_processes("Error del instalador con el código de salida: 1") == []
    assert installer_blocking_processes(f"Installer log is available at: {tmp_path / 'no.log'}") == []
    assert installer_blocking_processes(r"Installer log is available at: \\servidor\x\a.log") == []


def test_upgrade_failure_names_the_open_programs(tmp_path, monkeypatch):
    from winoptiai.apps.app_manager import upgrade_app_winget

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    log = tmp_path / "inst.log"
    _git_installer_log(log)

    class _Proc:
        pid = 4_100_000

        def __init__(self, cmd, stdout=None, **_k):
            stdout.write(
                (
                    "Iniciando instalación de paquete...\r\nError del instalador con el código de salida: 1\r\n"
                    f"El registro del instalador está disponible en: {log}\r\n"
                ).encode("utf-8")
            )

        def poll(self):
            return 1

    app = InstalledApp(app_id="g", name="Git", version="2.54.0", available_version="2.56.1", winget_id="Git.Git")
    ok, msg = upgrade_app_winget(app, poll_s=0.001, popen=_Proc)
    assert not ok
    assert "bash.exe" in msg and "git.exe" in msg and "Cierralos" in msg


def test_apps_list_refreshes_when_stale(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from winoptiai.core.safety_guard import QuarantineVault
    from winoptiai.core.sre_policy import SREPolicyEngine
    from winoptiai.ui.views.apps_view import AppsView

    view = AppsView(QuarantineVault(), SREPolicyEngine(), lambda *a, **k: None, lambda _m: None)
    assert view.needs_refresh()  # vacio
    view.apps = [InstalledApp(app_id="a", name="Alfa", version="1")]
    view._last_scan_ts = time.time()
    assert not view.needs_refresh()  # recien escaneado
    assert view.needs_refresh(now=time.time() + 31 * 60)  # mas de 30 min
    view.mark_stale()
    assert view.needs_refresh()  # el Vigia encontro novedades
    view._stale = False
    view._upgrading = True
    assert not view.needs_refresh(now=time.time() + 99 * 60)  # nunca durante una actualizacion
