# CLAUDE.md — Contexto de Ingenieria para Agentes (Claude Code / Antigravity / Codex)

Este archivo contiene el contexto operativo, arquitectonico y de diseno actual de **WinOptiAI** (`v0.5.13`) para garantizar continuidad exacta entre sesiones de agentes y desarrolladores.

## Perfil del Proyecto y Propietario

- **Propietario / Creditos:** Dairo (`dairo707-maker`, `https://github.com/dairo707-maker/WinOptiAI`). Economista; comunicarse en espanol claro en UI y documentacion.
- **Perfilado Multi-Equipo:** validado inicialmente en Lenovo `82FE` (`FKCN51WW(V3.14)`, i5-1135G7, Iris Xe `30.0.101.1960`, 16 GB RAM, Kingston NVMe, Windows 11 Build 26200), pero `bios_auditor.py` perfila dinamicamente cualquier hardware (Intel/AMD/ARM64, NVIDIA/AMD/Intel, SSD/HDD, RAM 8–128 GB) y calibra los umbrales SRE automaticamente.

## Reglas Inviolables de Diseno UI/UX

1. **Estetica "Obsidian Acrylic" / Dual Tema (`Alabaster Frost`):**
   - Bordes estrictamente rectos (`border-radius: 0px` en QSS y `DWMWCP_DONOTROUND` en `dwmapi.dll`). **Unica excepcion (decision del propietario, `v0.5.6`):** botones y etiquetas del panel superior (`QWidget#TopBar`) con `border-radius: 6px`.
   - **Roles de botones (`v0.5.6`):** `PrimaryAction` (1 por vista), `GhostAction` (neutro), `ModeTab` (pestanas de modo, subrayado al activarse) y acciones especificas de cada pestana por efecto: `RestoreAction` (salvia, restaurar/restablecer), `MoveAction` (ambar, mover a Cuarentena/Papelera/hardlink), `RiskAction` (oxido, eliminar definitivo o cerrar procesos). Asignar con `widgets.set_button_role()`; tonos apagados de la paleta (`tag_ok/warn/risk`), nunca neon.
   - **Texto nunca recortado (`v0.5.6`):** filas de botones con `widgets.FlowLayout` (pasan a otra fila), textos dinamicos con `widgets.AdaptiveButton.set_variants([largo, ..., corto])`, dialogos con `setMinimumSize` (nunca `setFixedSize`) y subtitulos con `setWordWrap(True)`. `tests/test_v056_ui_polish.py` recorre todas las vistas a 980x650 en oscuro y claro con `find_clipped_buttons`.
   - Lineas divisorias `1px` hairline, fondo translucido DWM Acrylic (`DWMWA_SYSTEMBACKDROP_TYPE = 3`).
   - Jerarquia monocromo / acero-hielo (`#E2E7ED`, `#9BA3AE`, `#0B0D10`). **Prohibidos los brillos neon, gradientes llamativos o colores saturados de "estetica IA".**
2. **Cero Emojis — 100% SVG Minimalistas:**
   - Prohibido usar emojis Unicode en `src/winoptiai/` (verificado por `tests/test_sre_and_hardware.py`), UI, etiquetas, notificaciones Tray o botones.
   - Usar exclusivamente iconos SVG geometricos de `assets/icons/*.svg` via `winoptiai.ui.svg_icons.load_svg_icon()`.
3. **Tipografia Embebida OFL:**
   - `Instrument Sans` (UI) + `IBM Plex Mono` (metricas, rutas, hashes, tags), cargadas desde `assets/fonts/`.
4. **Limpieza, Arranque Fluido y Concurrencia Segura:**
   - Arranque en 2 fases: pintar ventana principal antes de lanzar escaneos WMI/disco/retencion en `QThreadPool`.
   - Limite de concurrencia: maximo **2 tareas de almacenamiento simultaneas** (`storage_view.MAX_STORAGE_TASKS = 2`; global `main_window.MAX_CONCURRENT_TASKS = 4`) y proteccion por RAM libre minima; control cooperativo global (`Pausar`, `Guardar Pausa`, `Cancelar`, `Retomar Sesion`) en barra superior y cajon de tareas.
   - **Reglas criticas de PySide6 / Shiboken6 (lecciones P0 de `v0.5.1`–`v0.5.3`):**
     - **NUNCA** llamar a `super().__lt__()` dentro de `NumericTableItem.__lt__` o `NumericTreeItem.__lt__` (`ui/widgets.py`): en PySide6 vuelve a despachar al override de Python hasta desbordar la pila (`0xc0000005` en `shiboken6.abi3.dll`). Usar comparacion de texto propia en Python.
     - **NUNCA** llamar `setRowCount()` ni destruir widgets hijos (`deleteLater()` / `removeCellWidget()`) de forma sincrona dentro de un slot `clicked` (`thermal_bios_view.py`, `notifications_drawer.py`): diferir siempre la reconstruccion con `QTimer.singleShot(0, ...)`.
     - Conectar senales de `AsyncTask` con `Qt.QueuedConnection` explicita, limitar senales de progreso (~10/s o cambio de `%`) y usar carga perezosa (*lazy loading*) en `QTreeWidget` (`storage_view.py`).
     - En llamadas UAC (`ShellExecuteW`) fuera del hilo UI (`win32_bridge.run_elevated_command`), inicializar COM (`CoInitializeEx`) en el hilo trabajador.
   - **Monitoreo con historial (`v0.5.8`):** `core/metrics_history.py` guarda 1 punto/min (promedio de lecturas de 2 s via `MinuteAggregator`) en `%LOCALAPPDATA%\WinOptiAI\metrics.sqlite` (retencion 7 dias) usando una hebra unica (`MetricsHistory.submit`, FIFO: escribir y luego recargar). `ui/history_charts.py` dibuja con QPainter (monocromo, 1 px) RAM libre + umbral SRE, CPU % y marcadores B/L/D/E de `audit.jsonl`, y el acumulado de espacio liberado por tipo (AI Boost no cuenta: es RAM). Resumen va en `QScrollArea`: nunca poner reglas QSS sin selector en su viewport (se heredan a todos los hijos).
   - **Instancia unica (`v0.5.8`, `core/single_instance.py`):** mutex `Local\WinOptiAI-<hash>` antes del crash guard; la segunda copia avisa por `QLocalSocket` y termina. `--elevated-relaunch` espera 20 s al mutex. Causa de los AI Boost duplicados del 16/11: dos procesos abiertos.
   - **Modo Arbol (`v0.5.4`):** pestanas `Mapa jerarquico` (treemap squarified propio en `ui/treemap.py`, monocromo, 2 niveles, clic = entrar, doble clic = Explorador), `Carpetas y formatos` y `Archivos mas pesados` (top 100 global o agrupado por extension, filtro por categoria/extension, doble clic = Explorador con el archivo seleccionado). El analizador guarda solo tops acotados (60 subcarpetas por nivel, 30 archivos por extension, 100 global) para no inflar RAM.

## Invariantes de Seguridad del Sistema Operativo

- **INCIDENTE 17/11/2026 (Autolimpiar duplicados sobre todo el disco):** la v0.5.7 movio a Cuarentena 100.000+ copias "identicas" que NO sobraban (bibliotecas de Python de uv/Anaconda/3.13, DLL de Qt, `C:\Drivers`, datos de Teams/Zoom/navegadores), rompiendo esas instalaciones. Reglas desde `v0.5.9`:
  - `storage/program_guard.py`: Duplicados **nunca** recorre carpetas de programas, entornos, sistema ni configuracion (`AppData`, `Program Files`, `ProgramData`, `C:\Drivers`, `site-packages`, `.venv`, `node_modules`, `anaconda3`, carpetas ocultas `.algo`...) ni carpetas con marcas de instalacion (`pyvenv.cfg`, `conda-meta`, `.exe` junto a `.dll`).
  - "Carpetas copiadas" (dos carpetas con muchos archivos identicos) se marcan `protected_reason` y nunca se proponen: quitar archivos sueltos rompe la copia.
  - `select_duplicates_by_rule` conserva siempre al menos una copia del usuario; Autolimpiar muestra un resumen (copias, tamano, carpetas, protegidos) y pide confirmacion.
  - `create_operation_snapshot` guarda la lista COMPLETA (`snapshot_full.jsonl`); `quarantine_many` confirma el manifiesto cada 50 elementos y los lotes masivos cada 500 (si algo se interrumpe, lo movido queda registrado y restaurable).
  - `QuarantineVault.restore_items_bulk` restaura decenas de miles de elementos sin reescribir el manifiesto por cada uno y nunca sobrescribe un original existente.
- **Cierre total (`v0.5.9`):** `MainWindow._shutdown_everything` cancela todas las tareas (`controller.cancel()`), espera hasta `SHUTDOWN_WAIT_S` y llama `win32_bridge.terminate_app_child_processes()` (consolas elevadas rastreadas via `ShellExecuteExW` + descendientes con psutil), respetando `EXTERNAL_APP_NAMES` y PIDs protegidos (`protect_child_pid`, p. ej. el puente del actualizador). `app.main` remata con `os._exit` si quedara algun hilo activo: nunca debe quedar un proceso sin ventana. Todo bucle largo debe aceptar `controller` y detenerse en `stop_point`/`checkpoint`.
- **La Boveda y los datos de la app nunca se escanean (`v0.5.9`):** `safety_guard.is_internal_app_path` (carpeta `%LOCALAPPDATA%\WinOptiAI` y Bovedas registradas con `register_internal_root`) forma parte de `is_protected_path`; lo enviado a Cuarentena no reaparece en Arbol/Duplicados/Huerfanos.

- **NUNCA** leer contenido, previsualizar ni hidratar archivos con atributos `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS`, `FILE_ATTRIBUTE_OFFLINE`, `FILE_ATTRIBUTE_RECALL_ON_OPEN` o `FILE_ATTRIBUTE_UNPINNED` (`win32_bridge.is_cloud_only_file`).
  - **Carpetas vs. archivos (`v0.5.4`):** OneDrive marca casi todas sus CARPETAS con `UNPINNED` (`0x100000`) aunque esten en disco. En recorridos usar `win32_bridge.attrs_skip_entry(attrs, is_dir)`: en carpetas solo se omiten `OFFLINE`/`RECALL_ON_OPEN`/`RECALL_ON_DATA_ACCESS` (listar no hidrata); en archivos se mantiene la mascara completa. Antes Arbol/Duplicados ignoraban todo el contenido de OneDrive.
- **OneDrive Hibrido (`onedrive_optimizer.py`):** en local usa unicamente atributos Win32 Files On-Demand (`SetFileAttributesW` `+U -P`) protegiendo `.git`/`.venv`/`node_modules`; en nube usa Microsoft Graph OAuth 2.0 PKCE + cifrado local DPAPI (`CryptProtectData`), excluyendo elementos compartidos de terceros por defecto y moviendo solo a Papelera de OneDrive.
- **Proteccion de Archivos y Bloqueos:** en directorios pequeños se verifica `Rstrtmgr.dll` (`get_locking_processes`); para temporales masivos (`> 400` archivos) `junk_scanner.py` evita sesiones RPC lentas delegando la proteccion al kernel NTFS (`os.replace` / `WinError 32`). Re-verificar tamano + hash BLAKE3 justo antes de crear hardlinks NTFS.
- **NUNCA** tocar `PROTECTED_PATH_PREFIXES` ni procesos criticos (`PROTECTED_PROCESS_NAMES`, `get_foreground_pid()`, `os.getpid()` y `AI_FOREGROUND_AGENTS`).
- **Cuarentena y Rollback (`safety_guard.py`):** toda depuracion usa `QuarantineVault` transaccional (`manifest.json` escrito con `atomic_write_text`), `PreOpBackupManager`, y auto-purga al arranque solo de lotes `Basura:*` mayores a 30 dias. La purga usa `force_remove_tree` (quita solo-lectura, rutas largas `\\?\`), conserva el registro con el tamano restante si algo queda bloqueado y lo informa; "Vaciar todo" limpia tambien restos de `items/` sin registro (`list_orphan_entries`).
- **OneDrive Nube:** requiere un registro de aplicacion propio en Microsoft Entra ID (Client ID, cliente publico, redirect `http://localhost` exacto (la app envia `http://localhost:<puerto>` sin ruta; Entra ignora el puerto pero no la ruta, ver AADSTS50011 en `v0.5.5`), permisos delegados `User.Read Files.ReadWrite offline_access`). Cuentas de la Fundacion pueden requerir consentimiento del administrador del tenant.
- **Auditorias Hardware, S.M.A.R.T. y CBS (`bios_auditor.py`, `thermal_controller.py`):** nunca modificar NVRAM/SPI directamente; verificar cambios `powercfg` por lectura (`/q`); detectar procesos activos `Dism.exe`/`sfc.exe` para no encimar sesiones CBS concurrentes.
- **Crash Guard y Reporte Anonimizado (`crash_guard.py`, `crash_reporter.py`):** `faulthandler` (todos los hilos) + `excepthooks` + vigilante de bloqueos GUI (8 s) hacia `%LOCALAPPDATA%\WinOptiAI\crash.log`, `session_lock.json`, `RegisterApplicationRestart` y consulta `wevtutil` decodificada en ANSI (`mbcs`). Todo envio a GitHub Issues es opcional y anonimizado bajo revision del usuario. La URL prellenada no debe superar `crash_reporter.MAX_ISSUE_URL_CHARS = 3000`: sin sesion GitHub duplica la URL en `/login?return_to=` y desde ~5.900 caracteres responde HTTP 500 ("Whoops"); el informe completo va al portapapeles y a `%LOCALAPPDATA%\WinOptiAI\reports`.
- **Cuarentena instantanea (`v0.5.9`):** Supr, clic derecho, icono de caneca por fila (`fx.TrashColumnDelegate`, pintado, sin `setCellWidget`) y arrastrar desde el Explorador a la pestana Boveda. Se mueve con `quarantine_many(hash_max_bytes=64 MB)` en un `AsyncTask` sin tarea visible; al terminar: sonido de Papelera de Windows (`win32_bridge.play_recycle_sound`, silencio solo con esquema "Sin sonidos"), filas que se desvanecen, contador en la pestana Boveda y aviso "Deshacer" (`fx.UndoToast`). Las acciones ya no reescanean: quitan de los listados lo movido (`_remove_moved_from_lists`).
- **Animaciones (`ui/fx.py`):** cortas y sobrias; respetan "Mostrar animaciones en Windows" (`animations_enabled`). En pruebas usar `fx.set_animations_enabled(False)`.
- **Sesiones retomables (`task_control.py`):** `stop_point(controller)` es el punto seguro de parada de los motores (lanza `TaskCanceledError` o `TaskSaveRequested`). Los analisis de Duplicados y Arbol se lanzan con `run_async(..., resume_meta={...})`: "Guardar Pausa" crea una sesion `kind="rescan"` y Duplicados reutiliza las huellas de `HashCache` (`hash_cache.sqlite`). `Pausar` congela cualquier tarea que llame `controller.checkpoint()`; `Guardar Pausa` solo funciona en tareas que manejan `"save_pause"` y guardan un `TaskSessionRecord` (hoy unicamente `junk_clean`: limpieza de temporales y su reanudacion). Lanzar esas tareas con `_run_async(..., supports_save=True)`; las demas no muestran el boton.

## Comandos Clave (siempre con `uv` — en carpeta OneDrive usar `--no-sync`)

```powershell
# Ejecutar pruebas automatizadas (NUNCA declarar validado sin correr esto)
uv run --no-sync pytest -v

# Sincronizar entorno solo si se cambiaron dependencias en pyproject.toml
uv sync --extra dev --link-mode=copy

# Ejecutar la aplicacion en modo desarrollo
uv run --no-sync python -m winoptiai.app

# Compilar WinOptiAI-Portable.exe y WinOptiAI-Setup.exe (esperar exit code 0 antes de leer dist\)
uv run --no-sync python scripts/build_exe.py
```

## Convenciones de Git, Versionado y Notas

- Rama principal: `main`.
- Version unica en `VERSION` (actualmente `0.5.10`), sincronizada con `pyproject.toml`, `tests/test_sre_and_hardware.py` y `CHANGELOG.md`.
- En Windows con `gh release create`, escribir notas en archivo temporal y pasar `--notes-file`.
- Usar commits semanticos descriptivos en espanol (`feat(core): ...`, `fix(ui): ...`, `docs: ...`).
- Adjuntar `git notes` tecnicas con contexto de verificacion a los commits principales (`git log --show-notes`, `git push origin main "refs/notes/*"`).
