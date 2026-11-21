# AGENTS.md — Guia Multi-Agente (Antigravity, Claude Code, Codex, Cursor)

Este repositorio sigue el estandar de contexto compartido. Lea `CLAUDE.md` como referencia maestra de hardware, identidad visual corporativa TRODAI (`0px` Obsidian Navy `#0A0F1D` / Crisp White `#F8FAFC` con `#0EA5E9` / `#3B82F6`, cero emojis, `Space Grotesk` + `JetBrains Mono`), lecciones criticas de `PySide6`/`shiboken6` e invariantes de seguridad del sistema operativo (`v0.6.1`).

## Mapa de Modulos

- `src/winoptiai/app.py`: Arranque en 2 fases, QSS embebido, integracion `CrashGuard`, `RegisterApplicationRestart` y manejo de reinicio `--crash-restart`.
- `src/winoptiai/core/win32_bridge.py`: Puente `ctypes` a `dwmapi.dll`, `kernel32.dll`, `psapi.dll`, `Rstrtmgr.dll`, `shell32.dll` (`RunAs` con COM STA), `crypt32.dll` (DPAPI) y `user32.dll` (`get_foreground_pid`, `RegisterApplicationRestart`).
- `src/winoptiai/core/safety_guard.py`: Listas blancas OS/antivirus, `atomic_write_text`, `QuarantineVault` transaccional por lotes (`manifest.json`, SHA-256, auto-expiracion 30d de `Basura:*`) y `PreOpBackupManager`.
- `src/winoptiai/core/sre_policy.py`: Motor de politica hibrida SRE (calibracion dinamica RAM + histeresis 300 s + `audit.jsonl` y persistencia de acciones de auditoria).
- `src/winoptiai/core/task_control.py`: Control cooperativo (`TaskController`: pausa, guardar pausa, cancelacion, checkpoint) y `SessionManager` (`%LOCALAPPDATA%\WinOptiAI\sessions`).
- `src/winoptiai/core/crash_guard.py` & `crash_reporter.py`: `faulthandler` nativo, `excepthooks`, vigilante de bloqueos GUI (`8 s`), `session_lock.json`, consulta `wevtutil` (IDs `1000`/`1002` en ANSI `mbcs`) e informe anonimizado opcional hacia GitHub Issues.
- `src/winoptiai/core/notifications.py`: Centro de notificaciones persistente y consejero periodico de bajo ruido (`PeriodicAdvisor`).
- `src/winoptiai/core/telemetry.py`: Lector `pdh.dll` independiente de idioma (frecuencia CPU MHz, Turbo %, carga por nucleo y sonda termica ACPI/NVMe).
- `src/winoptiai/core/i18n.py` & `updater.py`: Soporte ES/EN/PT sincronizado con Inno Setup 6 y auto-actualizador desacoplado con verificacion SHA-256 contra GitHub Releases (`dairo707-maker/WinOptiAI`).
- `src/winoptiai/storage/`:
  - `junk_scanner.py`: Escaner/limpieza por lotes NTFS con omision de `Rstrtmgr.dll` sobre `>400` archivos, rutas OS/IA (`Windows Update`, `VS Code`, `HuggingFace`) y `resume_junk_session()`.
  - `duplicate_finder.py`: Deduplicador BLAKE3 en 4 etapas + reglas autolimpiador + re-verificacion antes de crear hardlinks NTFS.
  - `tree_analyzer.py` & `orphan_hunter.py`: Arbol jerarquico acotado (top-60 carpetas por nivel + heap top-100 pesados) y detector de residuos sin programa padre.
  - `onedrive_optimizer.py`: Optimizador hibrido Files On-Demand local + Microsoft Graph OAuth PKCE cifrado con DPAPI.
- `src/winoptiai/ai_optimizer/process_manager.py`: Telemetria RAM/`% CPU` con cache de handles `psutil`, `run_ai_boost()` (protege `self_pid`, ventana activa y agentes IA) y cazador de workers MCP zombis.
- `src/winoptiai/thermal_bios/`: `thermal_controller.py` (perfiles `powercfg` + verificacion `/q`) y `bios_auditor.py` (S.M.A.R.T., eventos 14d `Disk`/`Ntfs`/`WHEA`, TPM/BitLocker/HVCI, OEM BIOS >2a, `CHKDSK`/`DISM`/`SFC`/`WinSxS` con guardia contra sesiones activas).
- `src/winoptiai/ui/`: Shell `PySide6` Dual Tema (`main_window.py`, `theme.py`, `widgets.py`, `workers.py`, `svg_icons.py`, `system_tray.py`), vistas (`overview_view.py`, `storage_view.py` con casilla tri-estado "Seleccionar todo" y carga perezosa de arbol, `processes_view.py`, `thermal_bios_view.py`) y dialogos (`about_updater_dialog.py`, `notifications_drawer.py`, `crash_report_dialog.py`, `crash_send_dialog.py`).
- `scripts/build_exe.py`, `packaging/installer.iss` & `tests/`: Empaquetado PyInstaller `--onefile`, Inno Setup 6 con guardia `PrepareToInstall`, y suite de pruebas `test_*`.

## Checklist Obligatorio antes de Confirmar Cambios

1. Verificar cero emojis en `src/winoptiai/` y 100% de pruebas aprobadas ejecutando `uv run --no-sync pytest -v`.
2. Mantener `border-radius: 0px`, paleta monocromo Obsidian Acrylic / Alabaster Frost y diferir con `QTimer.singleShot(0, ...)` toda reconstruccion de tablas/layouts disparada desde widgets hijos (`setCellWidget` / botones dinamicos).
3. No introducir dependencias fuera de `pyproject.toml` sin actualizar `uv` (`uv sync --extra dev --link-mode=copy` en carpetas OneDrive).
4. Actualizar `VERSION`, `pyproject.toml`, `CHANGELOG.md`, `CLAUDE.md`/`AGENTS.md` (si aplica) y adjuntar `git note` al commit.
