"""Standalone Windows installer & uninstaller for WinOptiAI (0px Obsidian design)."""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import subprocess
import sys
import winreg

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "WinOptiAI"
UNINSTALL_KEY = r"Software\Microsoft\Windows\CurrentVersion\Uninstall\WinOptiAI"


def _bundle_root() -> Path:
    if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def _install_dir() -> Path:
    local_app = Path(os.environ.get("LOCALAPPDATA", str(Path.home() / "AppData" / "Local")))
    return local_app / "Programs" / APP_NAME


def _read_version() -> str:
    vf = _bundle_root() / "VERSION"
    return vf.read_text(encoding="utf-8").strip() if vf.exists() else "0.1.0"


def _create_shortcut(shortcut_path: Path, target_exe: Path, work_dir: Path) -> None:
    shortcut_path.parent.mkdir(parents=True, exist_ok=True)
    ps = (
        f"$ws = New-Object -ComObject WScript.Shell; "
        f"$s = $ws.CreateShortcut('{shortcut_path}'); "
        f"$s.TargetPath = '{target_exe}'; "
        f"$s.WorkingDirectory = '{work_dir}'; "
        f"$s.Description = 'WinOptiAI - Almacenamiento, Procesos IA y Termica'; "
        f"$s.Save()"
    )
    subprocess.run(
        ["powershell", "-NoProfile", "-Command", ps],
        capture_output=True,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        timeout=15,
    )


def _register_uninstall(install_dir: Path, exe_path: Path, version: str) -> None:
    uninstaller = install_dir / "WinOptiAI-Setup.exe"
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY) as key:
        winreg.SetValueEx(key, "DisplayName", 0, winreg.REG_SZ, APP_NAME)
        winreg.SetValueEx(key, "DisplayVersion", 0, winreg.REG_SZ, version)
        winreg.SetValueEx(key, "Publisher", 0, winreg.REG_SZ, "WinOptiAI Open Source")
        winreg.SetValueEx(key, "InstallLocation", 0, winreg.REG_SZ, str(install_dir))
        winreg.SetValueEx(key, "DisplayIcon", 0, winreg.REG_SZ, str(exe_path))
        winreg.SetValueEx(key, "UninstallString", 0, winreg.REG_SZ, f'"{uninstaller}" --uninstall')
        winreg.SetValueEx(key, "NoModify", 0, winreg.REG_DWORD, 1)
        winreg.SetValueEx(key, "NoRepair", 0, winreg.REG_DWORD, 1)


def perform_uninstall() -> None:
    inst = _install_dir()
    desktop_lnk = Path.home() / "Desktop" / f"{APP_NAME}.lnk"
    start_lnk = (
        Path(os.environ.get("APPDATA", ""))
        / "Microsoft"
        / "Windows"
        / "Start Menu"
        / "Programs"
        / f"{APP_NAME}.lnk"
    )
    for lnk in (desktop_lnk, start_lnk):
        if lnk.exists():
            lnk.unlink(missing_ok=True)
    try:
        winreg.DeleteKey(winreg.HKEY_CURRENT_USER, UNINSTALL_KEY)
    except OSError:
        pass
    app_exe = inst / f"{APP_NAME}.exe"
    if app_exe.exists():
        app_exe.unlink(missing_ok=True)


class InstallerWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.version = _read_version()
        self.setWindowTitle(f"Instalador {APP_NAME} v{self.version}")
        self.setFixedSize(520, 320)

        root = QWidget()
        self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        layout.setContentsMargins(24, 22, 24, 22)
        layout.setSpacing(14)

        title = QLabel(f"Instalar {APP_NAME} v{self.version}")
        title.setStyleSheet("font-size: 18px; font-weight: 600; color: #F1F3F5;")
        layout.addWidget(title)

        desc = QLabel(
            f"Destino: {_install_dir()}\n"
            "Incluye proteccion OneDrive, Restart Manager, IA Boost (EcoQoS) y control termico."
        )
        desc.setWordWrap(True)
        desc.setStyleSheet("font-size: 12px; color: #9BA3AE;")
        layout.addWidget(desc)

        self.chk_desktop = QCheckBox("Crear acceso directo en el Escritorio")
        self.chk_desktop.setChecked(True)
        layout.addWidget(self.chk_desktop)

        self.chk_launch = QCheckBox("Ejecutar WinOptiAI al finalizar la instalacion")
        self.chk_launch.setChecked(True)
        layout.addWidget(self.chk_launch)

        self.status = QLabel("Listo para instalar en perfil de usuario (sin modificar sistema).")
        self.status.setStyleSheet("font-size: 12px; color: #CBD5E1;")
        layout.addWidget(self.status)

        layout.addStretch()
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        self.cancel_btn = QPushButton("Cancelar")
        self.cancel_btn.clicked.connect(self.close)
        btn_row.addWidget(self.cancel_btn)

        self.install_btn = QPushButton("Instalar Ahora")
        self.install_btn.setObjectName("Primary")
        self.install_btn.clicked.connect(self._do_install)
        btn_row.addWidget(self.install_btn)
        layout.addLayout(btn_row)

        self.setStyleSheet(
            """
            * { border-radius: 0px; font-family: "Segoe UI", sans-serif; }
            QMainWindow, QWidget { background-color: #0E1116; color: #F1F3F5; }
            QPushButton {
                background-color: #1A1F27; color: #F1F3F5;
                border: 1px solid rgba(255,255,255,35); padding: 8px 16px; font-size: 12px;
            }
            QPushButton#Primary {
                background-color: #E2E7ED; color: #0B0D10; font-weight: 600;
            }
            QCheckBox { font-size: 12px; color: #F1F3F5; }
            """
        )

    def _do_install(self) -> None:
        self.install_btn.setEnabled(False)
        src_exe = _bundle_root() / "payload" / f"{APP_NAME}.exe"
        if not src_exe.exists():
            self.status.setText("Error: payload WinOptiAI.exe no encontrado en el instalador.")
            return

        dest_dir = _install_dir()
        dest_dir.mkdir(parents=True, exist_ok=True)
        dest_exe = dest_dir / f"{APP_NAME}.exe"
        shutil.copy2(src_exe, dest_exe)

        # Copy self as uninstaller if frozen
        if getattr(sys, "frozen", False):
            shutil.copy2(sys.executable, dest_dir / "WinOptiAI-Setup.exe")

        start_lnk = (
            Path(os.environ.get("APPDATA", ""))
            / "Microsoft"
            / "Windows"
            / "Start Menu"
            / "Programs"
            / f"{APP_NAME}.lnk"
        )
        _create_shortcut(start_lnk, dest_exe, dest_dir)
        if self.chk_desktop.isChecked():
            _create_shortcut(Path.home() / "Desktop" / f"{APP_NAME}.lnk", dest_exe, dest_dir)

        _register_uninstall(dest_dir, dest_exe, self.version)
        self.status.setText("Instalacion completada correctamente.")

        if self.chk_launch.isChecked():
            subprocess.Popen([str(dest_exe)], cwd=str(dest_dir))
        self.close()


def main() -> int:
    if "--uninstall" in sys.argv:
        perform_uninstall()
        return 0
    QApplication.setHighDpiScaleFactorRoundingPolicy(Qt.HighDpiScaleFactorRoundingPolicy.PassThrough)
    app = QApplication(sys.argv)
    win = InstallerWindow()
    win.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
