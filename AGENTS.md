# AGENTS.md — Guia Multi-Agente (Antigravity, Claude Code, Codex, Cursor)

Este repositorio sigue el estandar de contexto compartido. Lea `CLAUDE.md` como referencia maestra de hardware, identidad visual corporativa TRODAI (`0px` Obsidian Navy `#0A0F1D` / Crisp White `#F8FAFC` con `#0EA5E9` / `#3B82F6`, cero emojis, `Space Grotesk` + `JetBrains Mono`), lecciones criticas de `PySide6`/`shiboken6`, invariantes de seguridad del sistema operativo (`v0.6.5` publicada e instalada; `v0.6.6` y `v0.6.7` cerradas en repo local) y separacion respecto al repo hermano Android (`C:\Users\datg2\dev\WinOptiAI-Android`).

## Mapa de Modulos (`src/winoptiai/` — estado `v0.6.7`)

- `src/winoptiai/app.py`: Arranque en 2 fases, QSS embebido, `AppUserModelID ("TRODAI.WinOptiAI")`, `SingleInstanceLock` (`--elevated-relaunch` espera `30 s`), `DialogLocalizer` global (`QMessageBox` ES/EN/PT + roles), `CrashGuard` y `RegisterApplicationRestart`.
- `src/winoptiai/core/`:
  - `win32_bridge.py`: Puente `ctypes` a `dwmapi.dll`, `kernel32.dll` (incluye `SetThreadExecutionState`), `psapi.dll`, `Rstrtmgr.dll`, `shell32.dll`, `ntdll.dll` (`purge_standby_memory_list` con `SeProfileSingleProcessPrivilege`), `psutil` (`set_process_io_priority`), `crypt32.dll` (DPAPI) y `user32.dll`.
  - `safety_guard.py`: Listas blancas OS/antivirus, `atomic_write_text`, `QuarantineVault` transaccional por lotes (`manifest.json`, SHA-256, auto-expiracion 30d de `Basura:*`) y `PreOpBackupManager`.
  - `sre_policy.py`: Motor hibrido SRE (umbral dinamico RAM + histeresis `300 s`, `audit.jsonl`, acciones completadas, configuracion de columnas de tablas `table_column_widths` y horarios del Vigia diario).
  - `telemetry.py`: Lector `pdh.dll` independiente de idioma con `lazy_init=True` (CPU, Disco activo/cola/MB/s, Commit %, Page Reads, GPU VRAM/Engine via `PdhGetFormattedCounterArrayW`), `GetPerformanceInfo`, red `RX/TX MB/s`, `diagnose_bottleneck`, `SustainedBottleneckMonitor` (30 s) y sonda termica UAC (`probe_elevated_temperatures`).
  - `usage_telemetry.py`: Telemetria real de `ULTIMO USO` sin falsos `"Hoy"` por fondo ni `st_atime`: ventanas principales visibles (`EnumWindows`), `HKCU\...\Search\JumplistData`, `HKCU\...\Explorer\UserAssist` (ROT13, KNOWNFOLDERIDs, resolucion `.lnk` MS-SHLLINK, perfiles de navegador, aliases de suites), BAM/Prefetch (con UAC) y respaldo `Inst. YYYY-MM-DD`.
  - `daily_watch.py`: Vigia diario de solo lectura (horarios `9/14/19 h` con tolerancia post-suspension y cooldown `20 h`) que avisa en campana y bandeja cuando detecta actualizaciones `winget` o temporales >= 300 MB.
  - `task_control.py`, `single_instance.py` & `metrics_history.py`: Control cooperativo (`TaskController`), mutex de instancia unica (con rechazo en `ERROR_ACCESS_DENIED`), e historial `metrics.sqlite` (migracion SQLite no destructiva con Disco/Commit/VRAM/Red, 7 dias, hebra FIFO dedicada).
  - `crash_guard.py`, `crash_reporter.py`, `notifications.py`, `onboarding_check.py`, `help_catalog.py`, `i18n.py` & `updater.py`: Vigilante GUI (`8 s`), `wevtutil` (`1000`/`1002`), informes anonimizados, chequeo rapido 6 categorias, textos/tooltips ES/EN/PT y auto-actualizador SHA-256 contra `/releases/latest` (`WinOptiAI-Setup.exe`).
- `src/winoptiai/apps/`:
  - `app_manager.py`: Inventario Registro + `winget`, actualizaciones individuales o en lote (`upgrade_apps_winget` omitiendo entornos dev y saltos mayores), `Popen` sin timeout de 240s + logs en `%LOCALAPPDATA%\WinOptiAI\logs` + `protect_child_pid` + descarga directa WinINet, aviso de procesos abiertos (`running_app_processes`), lectura de bloqueos del instalador (`installer_blocking_processes`, `v0.6.6`), verificacion de rutas locales (`is_local_disk_path`), iconos MSI/EXE y desinstalacion + restos.
  - `startup_manager.py`: Escaneo de `Run`/`Startup`/`StartupApproved`, tareas programadas de inicio (`schtasks`), servicios automaticos de terceros (`sc config`), `read_last_boot_summary` (`Event ID 100` en Admin o Uptime), semaforo inteligente (`MANTENER`/`PAUSAR`/`DESACTIVAR`) y respaldo reversible.
- `src/winoptiai/storage/`:
  - `junk_scanner.py`: Escaner/limpieza por lotes NTFS sin `Rstrtmgr.dll` sobre `>400` archivos, rutas OS/IA y `resume_junk_session()`.
  - `duplicate_finder.py` & `program_guard.py`: Deduplicador BLAKE3 en 4 etapas protegiendo programas/entornos/carpetas copiadas, con reglas autolimpiador y re-verificacion antes de hardlinks NTFS.
  - `tree_analyzer.py`, `orphan_hunter.py` & `onedrive_optimizer.py`: Arbol acotado (top-60/nivel, heap top-100), residuos sin padre e integracion OneDrive local (`+U -P`) + Graph PKCE con DPAPI.
- `src/winoptiai/ai_optimizer/process_manager.py`: Telemetria RAM/`% CPU`/`E/S MB/s`, `run_ai_boost()`, `FocusModeManager` (EcoQoS + `IOPRIO_VERYLOW` + `SetThreadExecutionState` reversible), controles manuales por proceso y cazador de workers MCP zombis.
- `src/winoptiai/thermal_bios/`: `thermal_controller.py` y `bios_auditor.py` (S.M.A.R.T., eventos 14d, TPM/BitLocker/HVCI, OEM BIOS, `CHKDSK`/`DISM`/`SFC`/`WinSxS` con guardia CBS).
- `src/winoptiai/ui/`:
  - Shell y soporte: `main_window.py`, `theme.py` (pestanas `documentMode` sin base nativa blanca), `widgets.py` (`configure_interactive_columns` + persistencia, `configure_sortable_table`, `apply_table_tooltips`), `workers.py`, `svg_icons.py`, `system_tray.py` (incluye toggle `Modo Enfoque`), `fx.py` (`TrashColumnDelegate`, `UndoToast`), `context_menu.py` (clic derecho filtrado por seleccion), `dialog_localizer.py` (botones/roles ES/EN/PT) y `app_icons.py` (carga por tandas desde disco local).
  - Graficas y vistas: `history_charts.py` (series 24h/7d alternables CPU vs Disco/Commit, espacio liberado y medidores 2x2), `treemap.py` (`TreemapWidget` opaco), `overview_view.py` (Resumen sin scroll + diagnostico de cuello + Modo Enfoque), `storage_view.py`, `processes_view.py` (columna `E/S MB/s`, `Modo Enfoque`, `Purgar Standby` y controles EcoQoS/IO), `thermal_bios_view.py`, `apps_view.py` (`v0.6.6`), `startup_view.py` (Uptime + filtro tareas/servicios).
  - Dialogos: `about_updater_dialog.py`, `notifications_drawer.py`, `crash_report_dialog.py`, `crash_send_dialog.py`, `tour_dialog.py` (Tour 7 pasos).
- `scripts/build_exe.py`, `packaging/installer.iss` & `tests/`: Empaquetado PyInstaller `--onefile`, Inno Setup 6 y suite completa (`test_*` hasta `test_v067_monitoring_perf.py`).

## Repositorio Hermano Android (Separado Obligatoriamente)

- **Ruta local:** `C:\Users\datg2\dev\WinOptiAI-Android` (`dairo707-maker/WinOptiAI-Android`, fuera de OneDrive, Kotlin + Jetpack Compose, `:core:test` **48/48**, `:app:assembleDebug` OK).
- **Invariante critico:** Nunca publicar releases o artefactos Android en este repo de Windows porque `core/updater.py` consulta `/releases/latest` buscando `WinOptiAI-Setup.exe`.

## Checklist Obligatorio antes de Confirmar Cambios

1. Verificar cero emojis en `src/winoptiai/` y 100% de pruebas aprobadas ejecutando `uv run --no-sync pytest -v` (en entorno headless `offscreen`, las 2 capturas nativas de `test_v065_tabs_dark.py` se omiten con `SKIPPED`).
2. Mantener `border-radius: 0px` (excepto `QWidget#TopBar`), paleta TRODAI, tipografia `Space Grotesk` (`700`/`500`/`400`/`300`) + `JetBrains Mono` y reconstrucciones diferidas con `QTimer.singleShot(0, ...)` desde widgets hijos.
3. No escribir archivos temporales desde procesos elevados UAC ni leer iconos/carpetas desde rutas UNC/red (`is_local_disk_path`).
4. No introducir dependencias fuera de `pyproject.toml` sin actualizar `uv` (`uv sync --extra dev --link-mode=copy` en OneDrive).
5. Antes de cerrar un release, actualizar `VERSION`, `pyproject.toml`, `packaging/installer.iss`, `tests/test_sre_and_hardware.py`, `CHANGELOG.md`, `CLAUDE.md` y `AGENTS.md`, y adjuntar `git note` al commit.
