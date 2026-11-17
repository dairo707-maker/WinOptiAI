# Arquitectura Tecnica — WinOptiAI

## Vision General

WinOptiAI (`v0.5.8`) esta estructurado en cuatro capas desacopladas para garantizar bajo consumo en reposo (~40–50 MB RAM), arranque fluido en dos fases (`< 300 ms`), control cooperativo de tareas largas, recuperacion ante cierres inesperados y cero bloqueos en el hilo grafico:

1. **Capa de Puente Win32 (`src/winoptiai/core/win32_bridge.py`):**
   - `dwmapi.dll`: aplica `DWMWA_SYSTEMBACKDROP_TYPE = 3` (Acrylic oscuro / claro) y `DWMWA_WINDOW_CORNER_PREFERENCE = 1` (`DWMWCP_DONOTROUND`, bordes rectos `0px`).
   - `kernel32.dll` / `psapi.dll`: lectura de atributos OneDrive (`GetFileAttributesW`), hidratacion cero + deshidratacion Files On-Demand (`SetFileAttributesW` `+U -P`), enlaces duros NTFS (`CreateHardLinkW`), `SetProcessInformation(ProcessPowerThrottling)` (EcoQoS), `EmptyWorkingSet` y `RegisterApplicationRestart`.
   - `Rstrtmgr.dll`: sesiones del Windows Restart Manager para verificar bloqueos reales en conjuntos puntuales antes de tocar archivos (omitido automaticamente en lotes `> 400` temporales donde aplica fallback directo NTFS `WinError 32`).
   - `shell32.dll`, `ole32.dll`, `crypt32.dll`, `user32.dll`: envio a Papelera, elevacion UAC con inicializacion COM STA en hilos trabajadores, cifrado DPAPI para tokens Microsoft Graph y lectura de proceso activo en primer plano (`GetForegroundWindow`).

2. **Capa de Guardrails, Control Cooperativo y Telemetria de Fallos (`core/`):**
   - **`safety_guard.py`:** listas blancas inmutables de rutas del sistema operativo y procesos criticos/antivirus, escrituras atomicas resilientes (`atomic_write_text`), `QuarantineVault` transaccional por lotes (`manifest.json` + SHA-256 + auto-expiracion de `Basura:*` > 30 dias) y `PreOpBackupManager`.
   - **`sre_policy.py`:** guardia hibrido SRE cada `2 s` (`10 s` minimizado) con umbral dinamico segun RAM fisica, 3 muestras consecutivas, histeresis de `300 s`, `audit.jsonl` y seguimiento de acciones completadas.
   - **`task_control.py`:** `TaskController` (pausa, guardar pausa, cancelacion y checkpoints) y `SessionManager` (`%LOCALAPPDATA%\WinOptiAI\sessions`) para retomar limpiezas tras reiniciar o cerrar la app.
   - **`crash_guard.py` & `crash_reporter.py`:** `faulthandler` multi-hilo, hooks de excepcion Python/Qt, vigilante de congelamiento GUI (`8 s`), `session_lock.json`, consulta ANSI al Visor de eventos (`ID 1000`/`1002`), y generador de informe anonimizado revisado por el usuario hacia GitHub Issues.

3. **Motores de Dominio (`storage/`, `ai_optimizer/`, `thermal_bios/`):**
   - **`junk_scanner.py`:** limpieza de temporales y caches profundas (`Windows Update`, `DeliveryOptimization`, `VS Code`, `HuggingFace .locks`) con progreso ponderado, proteccion `_MEIPASS` y reanudacion de sesiones guardadas.
   - **`duplicate_finder.py`:** deduplicacion BLAKE3 en 4 etapas + autolimpiador por reglas + re-verificacion de tamano y hash antes de enlazar hardlinks NTFS.
   - **`tree_analyzer.py` & `onedrive_optimizer.py`:** analisis jerarquico acotado (`60` subcarpetas/nivel + heap top-100) y optimizador hibrido OneDrive Local + Microsoft Graph PKCE.
   - **`process_manager.py`:** `% CPU` real via cache de handles `psutil`, `run_ai_boost()` (excluye ventana en foco y agentes IA/IDE) y deteccion de workers MCP huerfanos.
   - **`thermal_controller.py` & `bios_auditor.py`:** perfiles `powercfg` verificados con `/q`, telemetria S.M.A.R.T. NVMe/SSD, eventos 14d (`Disk`/`Ntfs`/`WHEA`), postura TPM/BitLocker/HVCI, soporte multi-OEM BIOS y acciones UAC (`CHKDSK`, `DISM`, `SFC`, `WinSxS`) con deteccion previa de procesos CBS activos.

4. **Interfaz Dual Tema "Obsidian Acrylic / Alabaster Frost" (`src/winoptiai/ui/`):**
   - Construida sobre `PySide6` con fuentes OFL embebidas (`Instrument Sans` + `IBM Plex Mono`) e iconos SVG geometricos propios.
   - Fase 1 renderiza el shell y `CrashGuard`; Fase 2 ejecuta warmup WMI/disco/retencion en `QThreadPool`.
   - `QTreeWidget` con carga perezosa (*lazy loading* al expandir), casilla tri-estado `"Seleccionar todo"` sincronizada por sub-modo en `StorageView`, ordenacion segura sin recursion `super().__lt__()` y actualizaciones de widgets diferidas con `QTimer.singleShot(0, ...)`.
