"""v0.6.5: menu de clic derecho por apartado, botones Si/No traducidos, iconos de apps y sensores UAC."""

from __future__ import annotations

import base64
import os
import sys

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest  # noqa: E402

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication, QMessageBox, QPushButton, QWidget  # noqa: E402

from winoptiai.apps.app_manager import InstalledApp, msi_packed_guid, parse_display_icon  # noqa: E402
from winoptiai.core.telemetry import (  # noqa: E402
    _encode_ps,
    build_temperature_probe_script,
    clean_ps_stderr,
    interpret_temperature_probe,
)


@pytest.fixture(scope="module")
def qapp():
    return QApplication.instance() or QApplication([])


# ---------------------------------------------------------------- botones de dialogos
def test_message_box_buttons_follow_language_and_roles(qapp):
    from winoptiai.ui.dialog_localizer import localize_message_box, set_dialog_language

    box = QMessageBox(QMessageBox.Icon.Question, "t", "x", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    set_dialog_language("es")
    localize_message_box(box)
    texts = {box.standardButton(b): (b.text(), b.objectName()) for b in box.buttons()}
    assert texts[QMessageBox.StandardButton.Yes] == ("Sí", "PrimaryAction")
    assert texts[QMessageBox.StandardButton.No] == ("No", "GhostAction")

    warn = QMessageBox(QMessageBox.Icon.Warning, "t", "x", QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No)
    localize_message_box(warn, "pt")
    texts = {warn.standardButton(b): (b.text(), b.objectName()) for b in warn.buttons()}
    assert texts[QMessageBox.StandardButton.Yes] == ("Sim", "RiskAction")
    assert texts[QMessageBox.StandardButton.No][0] == "Não"
    set_dialog_language("xx")  # idioma desconocido -> espanol
    from winoptiai.ui.dialog_localizer import dialog_language

    assert dialog_language() == "es"


def test_global_filter_localizes_on_show(qapp):
    from winoptiai.ui.dialog_localizer import install_dialog_localizer

    install_dialog_localizer(qapp, "en")
    box = QMessageBox(QMessageBox.Icon.Question, "t", "x", QMessageBox.StandardButton.Ok | QMessageBox.StandardButton.Cancel)
    box.show()
    qapp.processEvents()
    names = sorted(b.text() for b in box.buttons())
    box.close()
    install_dialog_localizer(qapp, "es")
    assert names == ["Cancel", "OK"]
    assert all(b.minimumWidth() >= 96 for b in box.buttons())


# ---------------------------------------------------------------- menu contextual
def test_action_menu_mirrors_buttons(qapp):
    from winoptiai.ui.context_menu import build_action_menu
    from winoptiai.ui.widgets import AdaptiveButton

    host = QWidget()
    upd = QPushButton("Actualizar seleccionadas", host)
    unin = QPushButton("Desinstalar", host)
    unin.setEnabled(False)
    hidden = QPushButton("Hardlink NTFS", host)
    hidden.setVisible(False)
    scan = AdaptiveButton("Escanear Aplicaciones", host)
    scan.set_variants(["Escanear Aplicaciones", "Escanear"])
    clicks: list[str] = []
    upd.clicked.connect(lambda: clicks.append("upd"))
    extra_calls: list[str] = []

    menu = build_action_menu(
        host,
        row_buttons=[upd, unin, hidden],
        general_buttons=lambda: [scan],
        extras=lambda: [
            ("Abrir carpeta", lambda: None, False),  # no aplica: no se muestra
            None,
            ("Copiar nombre", lambda: extra_calls.append("copy"), True),
        ],
    )
    acts = menu.actions()
    labels = [a.text() for a in acts]
    # Solo lo que aplica: sin botones desactivados ni ocultos, sin separadores colgando
    assert labels == ["Actualizar seleccionadas", "", "Copiar nombre", "", "Escanear Aplicaciones"]
    acts[0].trigger()
    acts[2].trigger()
    assert clicks == ["upd"] and extra_calls == ["copy"]


def test_apps_menu_only_shows_what_applies_to_selection(qapp, tmp_path, monkeypatch):
    monkeypatch.setenv("LOCALAPPDATA", str(tmp_path))
    from winoptiai.core.safety_guard import QuarantineVault
    from winoptiai.core.sre_policy import SREPolicyEngine
    from winoptiai.ui.context_menu import build_action_menu
    from winoptiai.ui.views.apps_view import AppsView

    view = AppsView(QuarantineVault(), SREPolicyEngine(), lambda *a, **k: None, lambda _m: None)
    view.apps = [
        InstalledApp(app_id="a", name="Alfa", version="1.0", available_version="1.1", install_location=str(tmp_path)),
        InstalledApp(app_id="b", name="Beta", version="2.0"),
        InstalledApp(app_id="c", name="Gamma", version="3.0", protected_reason="Componente critico"),
    ]
    view._updates_checked = True
    view._render_apps()

    def labels_for(names: list[str]) -> list[str]:
        view.apps_table.clearSelection()
        for r in range(view.apps_table.rowCount()):
            if view.apps_table.item(r, 1).text() in names:
                view.apps_table.selectRow(r) if len(names) == 1 else view.apps_table.selectionModel().select(
                    view.apps_table.model().index(r, 0),
                    view.apps_table.selectionModel().SelectionFlag.Select
                    | view.apps_table.selectionModel().SelectionFlag.Rows,
                )
        return [a.text() for a in build_action_menu(view.apps_table, extras=view._row_menu_extras).actions() if a.text()]

    alfa = labels_for(["Alfa"])
    assert alfa[0] == "Actualizar a 1.1" and "Desinstalar" in alfa and "Abrir carpeta de instalacion" in alfa
    beta = labels_for(["Beta"])
    assert not any(t.startswith("Actualizar") for t in beta) and "Desinstalar" in beta
    gamma = labels_for(["Gamma"])
    assert "Desinstalar" not in gamma and not any(t.startswith("Actualizar") for t in gamma)
    both = labels_for(["Alfa", "Beta"])
    assert both[0] == "Actualizar 1 apps" or both[0] == "Actualizar a 1.1"
    assert "Desinstalar" not in both  # desinstalar es de a una app
    for lbls in (alfa, beta, gamma, both):
        assert "Actualizar todas" not in lbls and "Escanear Aplicaciones" not in lbls
        assert "Buscar Actualizaciones" not in lbls


def test_all_views_have_context_menus(qapp):
    from PySide6.QtCore import Qt

    from winoptiai.ui import context_menu

    calls: list[object] = []
    orig = context_menu.install_action_menu

    def spy(view, *a, **k):
        calls.append(view)
        return orig(view, *a, **k)

    import winoptiai.ui.views.apps_view as av
    import winoptiai.ui.views.processes_view as pv
    import winoptiai.ui.views.startup_view as sv

    for mod in (av, pv, sv):
        assert getattr(mod, "install_action_menu", None) is orig
    # Las tablas quedan con menu personalizado
    from winoptiai.ui.context_menu import install_action_menu
    from PySide6.QtWidgets import QTableWidget

    t = QTableWidget(2, 2)
    install_action_menu(t, general_buttons=[])
    assert t.contextMenuPolicy() == Qt.ContextMenuPolicy.CustomContextMenu


# ---------------------------------------------------------------- iconos de apps
def test_parse_display_icon_and_msi_guid():
    assert parse_display_icon('"C:\\Program Files\\App\\app.exe",0') == "C:\\Program Files\\App\\app.exe"
    assert parse_display_icon("C:\\Apps\\x.exe,-101") == "C:\\Apps\\x.exe"
    assert parse_display_icon("C:\\Apps\\icon.ico") == "C:\\Apps\\icon.ico"
    assert parse_display_icon("C:\\Apps\\readme.txt") == ""
    assert parse_display_icon("") == ""
    assert msi_packed_guid("{12345678-ABCD-EF01-2345-6789ABCDEF01}") == "87654321DCBA10FE32547698BADCFE10"
    assert msi_packed_guid("Google Chrome") == ""


def test_app_icon_loads_and_caches(qapp):
    from winoptiai.ui.app_icons import app_icon, cached_app_icon, icon_for_path

    app = InstalledApp(app_id="t:py", name="Python", version="3", icon_path=sys.executable)
    assert cached_app_icon(app) is None
    icon = app_icon(app)
    assert not icon.isNull()
    assert cached_app_icon(app) is icon
    assert not icon_for_path("").isNull()  # icono transparente para mantener alineado


# ---------------------------------------------------------------- sensores UAC
def test_temperature_script_survives_encoding():
    script = build_temperature_probe_script("C:\\Temp\\o'k.json")
    assert "$cpu=$null" in script and "$tz=Get-CimInstance" in script  # variables intactas
    assert "'C:\\Temp\\o''k.json'" in script  # comilla simple escapada
    decoded = base64.b64decode(_encode_ps(script)).decode("utf-16-le")
    assert decoded == script


def test_temperature_messages_are_honest():
    clixml = '#< CLIXML\r\n<Objs><Obj S="progress" RefId="0"></Obj></Objs>'
    assert clean_ps_stderr(clixml) == ""
    cancel = '#< CLIXML\r\n<Objs><S S="Error">Start-Process : La operacion fue cancelada por el usuario._x000D__x000A_</S></Objs>'
    assert "cancelada" in interpret_temperature_probe(None, cancel)[2]
    assert "no devolvio" in interpret_temperature_probe(None, clixml)[2]
    assert "no se pudo iniciar" in interpret_temperature_probe(None, "Acceso denegado")[2].lower()
    cpu, nvme, msg = interpret_temperature_probe({"cpu": 52.4, "nvme": 39})
    assert (cpu, nvme) == (52.4, 39) and "CPU 52 C" in msg
    # Valor fijo sin sentido de algunas placas: se descarta
    assert interpret_temperature_probe({"cpu": -273.1, "nvme": None})[0] is None


# ---------------------------------------------------------------- seguridad (revision automatica)
def test_icons_never_touch_network_paths():
    from winoptiai.apps.app_manager import guess_app_icon_path, is_local_disk_path

    for bad in (r"\\servidor\share\app.exe", "//servidor/share/app.exe", r"\\?\C:\x\app.exe",
                r"\\.\pipe\x", "app.exe", "C:app.exe", ""):
        assert not is_local_disk_path(bad), bad
    assert is_local_disk_path(sys.executable)
    assert parse_display_icon(r'"\\atacante\x\icon.ico",0') == ""
    app = InstalledApp(app_id="u", name="Red", version="1", install_location=r"\\atacante\carpeta")
    assert guess_app_icon_path(app) == ""


def test_elevated_probe_refuses_redirected_or_existing_targets():
    script = build_temperature_probe_script(r"C:\Temp\x\out.json")
    assert "CreateNew" in script and "ReparsePoint" in script
    assert "Set-Content" not in script


def test_probe_writes_into_private_random_folder(tmp_path):
    import subprocess

    out = tmp_path / "r.json"
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                    _encode_ps(build_temperature_probe_script(str(out)))], capture_output=True, timeout=90)
    assert out.exists() and out.read_text(encoding="utf-8-sig").startswith("{")
    # Si el archivo ya existe (posible trampa), no se sobrescribe
    out.write_text("trampa", encoding="utf-8")
    subprocess.run(["powershell", "-NoProfile", "-NonInteractive", "-EncodedCommand",
                    _encode_ps(build_temperature_probe_script(str(out)))], capture_output=True, timeout=90)
    assert out.read_text(encoding="utf-8") == "trampa"
