"""v0.6.9: actualizaciones (VC++/interactivo/Teams), progreso por elemento, info de app,
controladores en Windows Update, apps en segundo plano, Mantenimiento, Enfriar, previsualizador
y reportes por correo."""

from __future__ import annotations

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from winoptiai.apps.app_manager import (  # noqa: E402
    InstalledApp,
    can_upgrade,
    classify_winget_failure,
    parse_winget_show,
    retired_reason,
    upgrade_app_winget_interactive,
    upgrade_apps_winget,
    upgrade_block_reason,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- actualizaciones
def test_protected_runtimes_can_update_but_not_retired_or_critical():
    vc = InstalledApp(app_id="v", name="Microsoft Visual C++ v14 Redistributable (x64)", version="14.50",
                      available_version="14.52", protected_reason="Componente critico del sistema")
    assert upgrade_block_reason(vc) == "" and can_upgrade(vc)
    av = InstalledApp(app_id="b", name="Bitdefender Total Security", version="1", available_version="2",
                      protected_reason="Antivirus protegido")
    assert "Antivirus" in upgrade_block_reason(av) and not can_upgrade(av)
    teams = InstalledApp(app_id="t", name="Teams Machine-Wide Installer", version="1.4", available_version="1.8")
    assert retired_reason(teams) and not can_upgrade(teams)


def test_classify_interactive_and_uninstall_failures():
    epson = "Iniciando instalación de paquete...\r\nError del instalador con el código de salida: 1603\r\n"
    assert classify_winget_failure(0x8A150049, epson)[0] == "needs_interactive"
    teams = "Iniciando la desinstalación de paquete...\r\nError de desinstalación con el código de salida: 1603\r\n"
    assert classify_winget_failure(0x8A150030, teams)[0] == "uninstall_failed"


def test_interactive_upgrade_opens_installer_and_protects_pid():
    from winoptiai.core import win32_bridge

    calls = []

    class _P:
        pid = 4_200_000

        def __init__(self, cmd, **kw):
            calls.append(cmd)

    app = InstalledApp(app_id="e", name="Epson Software Updater", version="4.6", available_version="5.0",
                       winget_id="EPSON.SoftwareUpdater")
    ok, msg = upgrade_app_winget_interactive(app, popen=_P)
    assert ok and "--interactive" in calls[0] and "--silent" not in calls[0]
    assert 4_200_000 in win32_bridge._PROTECTED_CHILD_PIDS


def test_batch_reports_each_app_as_subtask():
    apps = [InstalledApp(app_id=f"a{i}", name=f"App{i}", version="1", available_version="2") for i in range(3)]
    events: list[tuple[str, str]] = []

    def sub(key, **kw):
        if "state" in kw:
            events.append((key, kw["state"]))

    res = upgrade_apps_winget(apps, upgrade_fn=lambda a: (a.name != "App1", "ok"), subtask_cb=sub)
    assert [ok for _a, ok, _m in res] == [True, False, True]
    assert events[:3] == [("a0", "pending"), ("a1", "pending"), ("a2", "pending")]
    assert ("a0", "ok") in events and ("a1", "error") in events and ("a2", "ok") in events
    assert apps[0].available_version == "" and apps[1].available_version == "2"


def test_worker_subtasks_are_tracked_and_injected(qapp):
    from winoptiai.ui.workers import AsyncTask

    def fn(subtask_cb=None):
        subtask_cb("x", label="Equis", state="running", pct=10)
        subtask_cb("x", state="ok")
        subtask_cb("y", label="Ye", state="error", detail="fallo")
        return 1

    task = AsyncTask("t", fn)
    task.run()
    snap = dict(task.subtask_snapshot())
    assert snap["x"]["state"] == "ok" and snap["x"]["pct"] == 100
    assert snap["y"]["state"] == "error" and task.subtask_counts() == (2, 2)


# ---------------------------------------------------------------- informacion de la app
def test_parse_winget_show_spanish():
    txt = (
        "Encontrado Google Chrome [Google.Chrome]\nVersión: 158\nEditor: Google LLC\n"
        "Descripción: Chrome is the official web browser from Google.\nPágina principal: https://www.google.com/chrome/\n"
        "Licencia: Freeware\n"
    )
    info = parse_winget_show(txt)
    assert info["publisher"] == "Google LLC" and info["license"] == "Freeware"
    assert info["description"].startswith("Chrome is") and info["homepage"].startswith("https://")
    assert "homepage" not in parse_winget_show("Página principal: http://inseguro.example\n")


def test_app_info_dialog_fills_details(qapp):
    from winoptiai.ui.dialogs.app_info_dialog import AppInfoDialog

    app = InstalledApp(app_id="z", name="Zoom Workplace", version="7.2.5", winget_id="Zoom.Zoom.EXE")
    dlg = AppInfoDialog(app)
    dlg.set_details({}, {"description": "Video platform.", "homepage": "https://zoom.us/", "license": "Proprietary"})
    assert "Video platform." in dlg.desc_lbl.text() and dlg.web_btn.isEnabled()
    dlg.close()


# ---------------------------------------------------------------- controladores / BIOS
def test_driver_update_parsing_and_summary():
    from winoptiai.thermal_bios.driver_updates import parse_driver_search, summarize_driver_updates

    raw = ('{"ok":true,"items":[{"title":"Lenovo Ltd. - Firmware - 1.51.0.0","cls":"Firmware","date":"2024-04-01"},'
           '{"title":"Intel - System","cls":"OtherHardware","date":"2017-09-19"}]}')
    ups, err = parse_driver_search(raw)
    assert not err and len(ups) == 2 and ups[0].is_firmware and ups[0].kind == "BIOS / firmware"
    assert "1 de BIOS/firmware" in summarize_driver_updates(ups)
    assert summarize_driver_updates([]).startswith("Todo al dia")
    assert parse_driver_search('{"ok":false,"error":"sin red"}')[1] == "sin red"


# ---------------------------------------------------------------- segundo plano
def test_background_apps_exclude_system_and_security():
    from winoptiai.ai_optimizer.background_apps import _is_excluded, caution_note

    assert _is_excluded("explorer.exe", r"C:\Windows\explorer.exe")
    assert _is_excluded("bdagent.exe", r"C:\Program Files\Bitdefender\bdagent.exe")
    assert _is_excluded("setup.exe", r"C:\Temp\setup.exe")
    assert not _is_excluded("whatsapp.root.exe", r"C:\Program Files\WindowsApps\WhatsApp\WhatsApp.Root.exe")
    assert "OneDrive" in caution_note("onedrive.sync.service.exe")


# ---------------------------------------------------------------- Registro
def test_registry_broken_rules(tmp_path):
    from winoptiai.maintenance.registry_cleaner import extract_command_path, path_is_missing

    assert extract_command_path('"C:\\Program Files\\App\\uninst.exe" /S') == "C:\\Program Files\\App\\uninst.exe"
    assert extract_command_path("C:\\Apps\\x.exe --arg") == "C:\\Apps\\x.exe"
    assert extract_command_path("rundll32.exe shell32.dll,Foo") == "rundll32.exe"
    existing = tmp_path / "ok.exe"
    existing.write_bytes(b"MZ")
    assert not path_is_missing(str(existing))
    assert path_is_missing(str(tmp_path / "borrado.exe"))
    assert not path_is_missing(r"\\servidor\share\app.exe")  # red: nunca se considera rota
    assert not path_is_missing(r"C:\Windows\System32\rundll32.exe")


def test_registry_clean_backs_up_before_deleting(tmp_path, monkeypatch):
    from winoptiai.maintenance import registry_cleaner as rc

    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    calls: list[tuple] = []

    class _Res:
        def __init__(self, code=0):
            self.returncode = code
            self.stderr = ""

    def fake_reg(*args, timeout=30.0):
        calls.append(args)
        if args[0] == "export":
            Path(args[2]).write_text("Windows Registry Editor Version 5.00\n", encoding="utf-16")
        return _Res(0)

    monkeypatch.setattr(rc, "_reg", fake_reg)
    entries = [
        rc.BrokenEntry("open_with", "HKCU", r"Software\Classes\Applications\viejo.exe", name="viejo.exe", target="C:\\x.exe"),
        rc.BrokenEntry("app_path", "HKLM", r"Software\Microsoft\Windows\CurrentVersion\App Paths\y.exe", name="y.exe", target="C:\\y.exe"),
    ]
    done, admin, folder = rc.clean_entries(entries)
    assert [c[0] for c in calls] == ["export", "export", "delete"]  # respaldo antes de borrar
    assert len(done) == 1 and len(admin) == 1 and (folder / "manifest.json").exists()
    assert "reg delete" in rc.elevated_delete_command(admin)


# ---------------------------------------------------------------- unidades
def test_volume_parsing_and_ssd_never_defragmented():
    from winoptiai.maintenance.drives import parse_volumes, ssd_health_summary

    raw = ('[{"letter":"C","label":"Windows-SSD","fs":"NTFS","size":1000,"free":500,"media":"SSD","bus":"NVMe",'
           '"health":"Healthy","model":"KINGSTON","wear":3,"temp":38,"hours":1200},'
           '{"letter":"D","media":"HDD","bus":"SATA","health":"Warning","wear":-1,"temp":-1,"hours":-1}]')
    vols = parse_volumes(raw)
    assert vols[0].is_ssd and vols[0].recommended_action == "ReTrim (TRIM)"
    assert vols[1].recommended_action == "Analizar y desfragmentar"
    assert "vida usada 3%" in ssd_health_summary(vols[0])
    assert vols[1].health_label == "Advertencia"


def test_maintenance_tab_exists(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from winoptiai.ui.main_window import MainWindow

    win = MainWindow()
    try:
        assert win.stack.count() == 7
        assert win.stack.widget(6) is win.maintenance_view
        assert hasattr(win.overview_view, "cool_btn")
    finally:
        win._force_quit = True
        win.close()


# ---------------------------------------------------------------- previsualizador y reportes
def test_preview_rules(tmp_path):
    from winoptiai.ui.dialogs.file_preview_dialog import can_preview, preview_kind

    assert preview_kind("a.PDF") == "pdf" and preview_kind("b.mp4") == "media" and preview_kind("c.csv") == "text"
    assert preview_kind("d.exe") == ""
    f = tmp_path / "x.txt"
    f.write_text("hola", encoding="utf-8")
    assert can_preview(str(f)) == (True, "")
    assert not can_preview(r"\\servidor\x.txt")[0]
    assert not can_preview(str(tmp_path / "no.txt"))[0]


def test_reports_go_by_email_without_github():
    from urllib.parse import parse_qs, urlparse

    from winoptiai.core import crash_reporter as cr

    url, trunc = cr.build_mailto_url("[Error] v0.6.9", "linea\n" * 2000)
    assert url.startswith(f"mailto:{cr.REPORT_EMAIL}?") and trunc and len(url) <= cr.MAX_MAILTO_CHARS
    short, t2 = cr.build_mailto_url("t", "corto")
    assert not t2 and parse_qs(urlparse(short).query)["body"] == ["corto"]
