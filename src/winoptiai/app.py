"""Application entry point with fluid startup, embedded fonts, persisted theme and crash guard."""

from __future__ import annotations

import os
import sys

from PySide6.QtCore import QThreadPool, Qt
from PySide6.QtWidgets import QApplication

from .core.crash_guard import CrashGuard
from .core.single_instance import SingleInstanceLock
from .core.sre_policy import SREPolicyEngine
from .core.win32_bridge import register_application_restart, terminate_app_child_processes
from .ui.main_window import CRASH_RESTART_ARG, ELEVATED_RELAUNCH_ARG, MainWindow
from .ui.svg_icons import load_svg_icon
from .ui.theme import build_obsidian_qss, register_embedded_fonts


def _notify_running_instance(key: str) -> None:
    """Pedir a la instancia ya abierta que muestre su ventana (tuberia local)."""
    from PySide6.QtCore import QCoreApplication
    from PySide6.QtNetwork import QLocalSocket

    _app = QCoreApplication.instance() or QCoreApplication(sys.argv)
    sock = QLocalSocket()
    sock.connectToServer(key)
    if sock.waitForConnected(1500):
        sock.write(b"show")
        sock.flush()
        sock.waitForBytesWritten(1000)
        sock.disconnectFromServer()


def _start_activation_server(key: str, on_activate):
    from PySide6.QtNetwork import QLocalServer

    server = QLocalServer()
    QLocalServer.removeServer(key)
    if not server.listen(key):
        return server

    def _on_conn() -> None:
        while server.hasPendingConnections():
            conn = server.nextPendingConnection()
            if conn is not None:
                conn.disconnected.connect(conn.deleteLater)
                conn.disconnectFromServer()
            on_activate()

    server.newConnection.connect(_on_conn)
    return server


APP_USER_MODEL_ID = "TRODAI.WinOptiAI"


def _set_app_user_model_id() -> None:
    """v0.6.1: identidad propia en la barra de tareas (coincide con los accesos del instalador).

    Sin esto Windows agrupa la ventana bajo python.exe o bajo un acceso anclado viejo y muestra
    el icono guardado en su cache en lugar del icono actual de la app.
    """
    try:
        import ctypes

        ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(APP_USER_MODEL_ID)
    except Exception:  # noqa: BLE001 - no Windows o shell32 sin la funcion
        pass


def _app_window_icon():
    """Icono de ventana/barra de tareas: el mismo .ico a color del ejecutable (Hexa-Vault).

    Antes se usaba brand.svg teñido gris claro (#E2E7ED), casi invisible en barra clara.
    """
    from PySide6.QtGui import QIcon

    from . import get_base_dir

    ico = get_base_dir() / "assets" / "icons" / "winoptiai.ico"
    if ico.exists():
        icon = QIcon(str(ico))
        if not icon.isNull():
            return icon
    return load_svg_icon("brand", color="#0EA5E9", size=32)


def main() -> int:
    # v0.5.8: instancia unica. Dos procesos abiertos duplicaban AI Boost automatico y
    # registros de audit.jsonl (16/11 22:45:35). Se comprueba antes del crash guard para no
    # pisar session_lock.json de la instancia en curso. Tras "Elevar Admin" se espera a que la
    # instancia anterior termine de cerrarse.
    instance_lock = SingleInstanceLock()
    if not instance_lock.acquire(wait_ms=30000 if ELEVATED_RELAUNCH_ARG in sys.argv else 0):
        _notify_running_instance(instance_lock.key)
        return 0

    # v0.5.1: telemetria post-mortem local antes de crear cualquier objeto Qt.
    crash_guard = CrashGuard()
    crash_guard.install()
    crash_guard.begin_session()
    # v0.5.3: si Windows termina la app (fallo nativo o "No responde"), WER la reabre con este
    # argumento y el aviso de envio de informe aparece de inmediato. Solo en el .exe: en modo
    # desarrollo reabriria python.exe sin el modulo.
    if getattr(sys, "frozen", False):
        register_application_restart(CRASH_RESTART_ARG)

    _set_app_user_model_id()
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    app = QApplication(sys.argv)
    app.setApplicationName("WinOptiAI")
    app.setQuitOnLastWindowClosed(False)
    crash_guard.install_qt_message_handler()
    app.aboutToQuit.connect(crash_guard.mark_clean_exit)

    policy = SREPolicyEngine()
    register_embedded_fonts(app)
    app.setStyleSheet(build_obsidian_qss(policy.config.theme_mode))
    app.setWindowIcon(_app_window_icon())

    window = MainWindow(crash_guard=crash_guard, auto_restarted=CRASH_RESTART_ARG in sys.argv)
    activation_server = _start_activation_server(instance_lock.key, window.restore_from_tray)  # noqa: F841
    if "--minimized" not in sys.argv:
        window.show()

    code = app.exec()
    # v0.5.9: cierre TOTAL tambien si se salio por otra via (cierre de sesion de Windows, etc.).
    res = window._shutdown_everything()
    crash_guard.mark_clean_exit()
    instance_lock.release()
    if res.get("pending_tasks") or QThreadPool.globalInstance().activeThreadCount() > 0:
        # Ninguna tarea puede seguir viva sin ventana: terminar el proceso por completo. Lo movido a
        # la Boveda ya quedo registrado (confirmacion por lotes de 50 / 500).
        crash_guard.write_log_block("CIERRE FORZADO", "Tareas aun activas al salir: proceso terminado.")
        terminate_app_child_processes()
        os._exit(int(code or 0))
    return code


if __name__ == "__main__":
    raise SystemExit(main())
