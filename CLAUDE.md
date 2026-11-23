# CLAUDE.md — Contexto de Ingenieria para Agentes (Claude Code / Antigravity / Codex)

Este archivo contiene el contexto operativo, arquitectonico y de diseno actual de **WinOptiAI · by TRODAI** (`v0.6.6` confirmada en repo local; ultimo binario publicado `v0.6.5`) para garantizar continuidad exacta entre sesiones de agentes y desarrolladores.

## Perfil del Proyecto y Propietario

- **Propietario / Creditos:** Dairo (`dairo707-maker`, `https://github.com/dairo707-maker/WinOptiAI`). Economista; comunicarse en espanol claro en UI y documentacion.
- **Perfilado Multi-Equipo:** validado inicialmente en Lenovo `82FE` (`FKCN51WW(V3.14)`, i5-1135G7, Iris Xe `30.0.101.1960`, 16 GB RAM, Kingston NVMe, Windows 11 Build 26200), pero `bios_auditor.py` perfila dinamicamente cualquier hardware (Intel/AMD/ARM64, NVIDIA/AMD/Intel, SSD/HDD, RAM 8–128 GB) y calibra los umbrales SRE automaticamente.

## Reglas Inviolables de Diseno UI/UX

1. **Estetica "Obsidian Acrylic" / Dual Tema (`Alabaster Frost`):**
   - Bordes estrictamente rectos (`border-radius: 0px` en QSS y `DWMWCP_DONOTROUND` en `dwmapi.dll`). **Unica excepcion (decision del propietario, `v0.5.6`):** botones y etiquetas del panel superior (`QWidget#TopBar`) con `border-radius: 6px`.
   - **Roles de botones (`v0.5.6`):** `PrimaryAction` (1 por vista), `GhostAction` (neutro), `ModeTab` (pestanas de modo, subrayado al activarse) y acciones especificas de cada pestana por efecto: `RestoreAction` (salvia, restaurar/restablecer), `MoveAction` (ambar, mover a Cuarentena/Papelera/hardlink), `RiskAction` (oxido, eliminar definitivo o cerrar procesos). Asignar con `widgets.set_button_role()`; tonos apagados de la paleta (`tag_ok/warn/risk`), nunca neon.
   - **Texto nunca recortado (`v0.5.6`):** filas de botones con `widgets.FlowLayout` (pasan a otra fila), textos dinamicos con `widgets.AdaptiveButton.set_variants([largo, ..., corto])`, dialogos con `setMinimumSize` (nunca `setFixedSize`) y subtitulos con `setWordWrap(True)`. `tests/test_v056_ui_polish.py` recorre todas las vistas a 980x650 en oscuro y claro con `find_clipped_buttons`.
   - Lineas divisorias `1px` hairline, fondo translucido DWM Acrylic (`DWMWA_SYSTEMBACKDROP_TYPE = 3`).
   - Paleta corporativa **TRODAI**: Oscuro **Obsidian Navy** (`#0A0F1D` / `#0F1628`) y Claro **Crisp White** (`#F8FAFC` / `#EEF2F7`) con acentos **Cyber Cyan** (`#0EA5E9`) y **Governance Blue** (`#3B82F6`) y semaforos legibles. **Prohibidos los brillos neon, gradientes llamativos o colores saturados de "estetica IA".**
2. **Cero Emojis — 100% SVG Minimalistas:**
   - Prohibido usar emojis Unicode en `src/winoptiai/` (verificado por `tests/test_sre_and_hardware.py`), UI, etiquetas, notificaciones Tray o botones.
   - Usar exclusivamente iconos SVG geometricos de `assets/icons/*.svg` via `winoptiai.ui.svg_icons.load_svg_icon()`.
3. **Tipografia Embebida OFL:**
   - `Space Grotesk` (UI: Light 300, Regular 400, Medium 500, Bold 700; nunca 600) + `JetBrains Mono` (solo KPIs, ejes de graficas, rutas, hashes, tags y logs), cargadas desde `assets/fonts/` (con respaldo legacy `Instrument Sans` / `IBM Plex Mono`).
4. **Limpieza, Arranque Fluido y Concurrencia Segura:**
   - Arranque en 2 fases: pintar ventana principal antes de lanzar escaneos WMI/disco/retencion en `QThreadPool`. Telemetria PDH diferida en hilo secundario (`lazy_init=True` + `ensure_initialized`).
   - Limite de concurrencia: maximo **2 tareas de almacenamiento simultaneas** (`storage_view.MAX_STORAGE_TASKS = 2`; global `main_window.MAX_CONCURRENT_TASKS = 4`) y proteccion por RAM libre minima; control cooperativo global (`Pausar`, `Guardar Pausa`, `Cancelar`, `Retomar Sesion`) en barra superior y cajon de tareas.
   - **Reglas criticas de PySide6 / Shiboken6 (lecciones P0 de `v0.5.1`–`v0.5.3`):**
     - **NUNCA** llamar a `super().__lt__()` dentro de `NumericTableItem.__lt__` o `NumericTreeItem.__lt__` (`ui/widgets.py`): en PySide6 vuelve a despachar al override de Python hasta desbordar la pila (`0xc0000005` en `shiboken6.abi3.dll`). Usar comparacion de texto propia en Python.
     - **NUNCA** llamar `setRowCount()` ni destruir widgets hijos (`deleteLater()` / `removeCellWidget()`) de forma sincrona dentro de un slot `clicked` (`thermal_bios_view.py`, `notifications_drawer.py`): diferir siempre la reconstruccion con `QTimer.singleShot(0, ...)`.
     - Conectar senales de `AsyncTask` con `Qt.QueuedConnection` explicita, limitar senales de progreso (~10/s o cambio de `%`) y usar carga perezosa (*lazy loading*) en `QTreeWidget` (`storage_view.py`).
     - En llamadas UAC (`ShellExecuteW`) fuera del hilo UI (`win32_bridge.run_elevated_command`), inicializar COM (`CoInitializeEx`) en el hilo trabajador.
   - **Monitoreo con historial (`v0.5.8`–`v0.6.1`):** `core/metrics_history.py` guarda 1 punto/min (promedio de lecturas de 2 s via `MinuteAggregator`) en `%LOCALAPPDATA%\WinOptiAI\metrics.sqlite` (retencion 7 dias) usando una hebra unica (`MetricsHistory.submit`, FIFO: escribir y luego recargar). `ui/history_charts.py` dibuja con QPainter (`TimeSeriesChart`, `FreedSpaceChart`, `_FreedLegend`, `SystemGaugesWidget` 2x2) con margenes dinamicos via `QFontMetrics` para no recortar ejes Y ni leyendas. Desde `v0.6.0`, `Resumen` va sin `QScrollArea` para caber limpio en `980x650`.
   - **Instancia unica (`v0.5.8` / `v0.6.2`, `core/single_instance.py`):** mutex `Local\WinOptiAI-<hash>` antes del crash guard; la segunda copia avisa por `QLocalSocket` y termina (tambien rechaza arranque duplicado en `ERROR_ACCESS_DENIED`). `--elevated-relaunch` espera 30 s al mutex y usa `run_elevated_command(..., track=False, directory=...)` para que `_shutdown_everything` no mate la nueva instancia elevada (`v0.6.2`). Causa de los AI Boost duplicados del 16/11: dos procesos abiertos.
   - **Modo Arbol (`v0.5.4`):** pestanas `Mapa jerarquico` (treemap squarified propio en `ui/treemap.py`, opaco con paleta por categoria, 2 niveles, clic = entrar, doble clic = Explorador, breadcrumbs clickables), `Carpetas y formatos` y `Archivos mas pesados` (top 100 global o agrupado por extension, filtro por categoria/extension, doble clic = Explorador con el archivo seleccionado). El analizador guarda solo tops acotados (60 subcarpetas por nivel, 30 archivos por extension, 100 global) para no inflar RAM.

## Consolidado v0.6.6 (22/11/2026)

- **Estado de ramas/repos al 22/11/2026:**
  - `WinOptiAI` Windows `v0.6.6` verificada localmente (binario instalado anterior `v0.6.5` en `%LOCALAPPDATA%\Programs\WinOptiAI\WinOptiAI.exe`; pendiente compilar/publicar release `v0.6.6` o continuar hacia `v0.6.7` Monitoreo Pro cuando lo indique el propietario).
  - La carpeta local `.historial-ia/` queda sin rastrear en git.
- **Revision real de actualizaciones (22/11):** 6 de 7 correctas y verificadas en el Registro (Chrome 158.0.8127.37, Python 3.13.17, Zoom 7.2.5, WinRAR 7.23, Python Launcher 3.15.2, PDF24 11.35). Git 2.56.1 fallo porque `bash.exe` estaba abierto (Inno: "Please terminate those processes").
- `app_manager.installer_blocking_processes`: lee el registro del instalador que indica winget (solo ruta local) y nombra los programas abiertos; `upgrade_app_winget` lo usa en el mensaje de fallo.
- `apps_view`: `needs_refresh` (vacio, `mark_stale`, o >30 min; nunca durante una actualizacion), re-escaneo 1,5 s despues de `_run_upgrades`, auditoria tambien de fallos ("Actualizar App (fallo)"). `main_window._switch_tab` refresca al abrir Aplicaciones; el Vigia diario llama `mark_stale` si hay novedades.
- **Repo hermano Android (privado aparte):** `dairo707-maker/WinOptiAI-Android` (local `C:\Users\datg2\dev\WinOptiAI-Android`, fuera de OneDrive; `:core:test` **46/46**, `:app:assembleDebug` OK; ampliado con ficha unificada por item, seleccion externa, reproductor nativo offline video/audio, orden/filtro/agrupacion por tipo de archivo, `HashCache`, residuos WhatsApp/temporales/carpetas vacias, Papelera vaciar/huerfanos y registro semanal de espacio recuperado). Motivo de separacion: `core/updater.py` usa `/releases/latest` y busca `WinOptiAI-Setup.exe`; un release Android en este repo romperia las actualizaciones de Windows.

## Cambios Consolidados v0.6.5 (22/11/2026, Claude Code)

- **Pestanas `setDocumentMode(True)` (`theme.py`):** `QTabBar { qproperty-drawBase: 0 }` + fondo propio en `QTabBar::tab`; antes Windows pintaba una base blanca detras en modo oscuro.
- **Dialogos (`ui/dialog_localizer.py`):** filtro global instalado en `app.py`; al mostrarse un `QMessageBox`/`QDialogButtonBox` traduce los botones estandar (ES/EN/PT, `set_dialog_language` en `_on_language_changed`) y asigna roles (`PrimaryAction` / `GhostAction`, `RiskAction` si el icono es Advertencia/Critico). No hace falta tocar cada llamada a `QMessageBox`.
- **Menu contextual (`ui/context_menu.py`, decision del propietario):** muestra SOLO lo que aplica a la seleccion; nunca las acciones generales de la barra (Actualizar todas, Escanear, Buscar...) ni opciones que no aplican (se ocultan, no se desactivan). `install_action_menu(view, row_buttons, extras)`; extras = `(texto, fn, aplica)` y `None` = separador. Aplicaciones: "Actualizar a X" solo con nueva version, Desinstalar solo 1 app no protegida; Inicio: Desactivar/Reactivar segun estado; Almacenamiento: `_storage_selection_actions` por modo.
- **Iconos de apps (`ui/app_icons.py`, `app_manager.parse_display_icon/guess_app_icon_path/msi_packed_guid`):** `QFileIconProvider` 16 px opacidad 0.85, cache por ruta; fuentes: DisplayIcon -> `Installer\Products\<GUID empaquetado>\ProductIcon` -> .exe de InstallLocation -> `App Paths`. `apps_view._load_icon_batch` carga 6 por vuelta. Nunca lee archivos solo-nube.
- **Sensores UAC (`core/telemetry.probe_elevated_temperatures`):** script con `-EncodedCommand` (antes `$variables` se expandian en la PowerShell externa). **El proceso elevado NUNCA escribe archivos** (revision de seguridad: desvio por junction/TOCTOU): via UAC devuelve las lecturas en el codigo de salida (`PROBE_EXIT_BASE + cpu_decimas*1000 + nvme`, leido con `Start-Process -PassThru`, `decode_probe_exit_code`); si la app ya es admin, JSON por stdout. `clean_ps_stderr` quita CLIXML; `interpret_temperature_probe` da mensajes reales.
- **Rutas de red (`app_manager.is_local_disk_path`):** iconos y carpetas solo de discos locales (nunca UNC, dispositivo ni unidades de red mapeadas: fuga NTLM).
- **Pruebas:** `tests/test_v065_tabs_dark.py`, `tests/test_v065_menus_dialogs_icons.py`.

## Cambios Consolidados v0.6.4 (22/11/2026, Claude Code)

- **Actualizaciones confiables y rapidas (`apps/app_manager.py`):** diagnostico real con Antigravity IDE 2.8.0 desde la App.
  - `upgrade_app_winget` ya no usa `subprocess.run(timeout=240)`: lanza `Popen` con salida a `%LOCALAPPDATA%\WinOptiAI\logs\winget-upgrade-<id>.log`, `protect_child_pid(winget)` (sobrevive a `_shutdown_everything`) y espera sondeando (fase `winget_phase`, minutos). Cancelar o pasar `WINGET_UPGRADE_MAX_WAIT_S` (45 min) solo deja de esperar: **NUNCA matar winget ni el instalador**.
  - `interpret_winget_result`: 0 / "instalado correctamente" = ok; `0x8A15002B` o "ninguna actualizacion aplicable" = al dia.
  - `ensure_winget_direct_download`: `settings.json` de winget con `network.downloader = wininet` (Delivery Optimization fallaba con `0x80D02002` tras 60 s). Respaldo `settings.json.winoptiai.bak`; si el archivo tiene comentarios al final de linea, no se toca.
  - `running_app_processes` + `apps_view._confirm_apps_closed`: pide cerrar la app antes de actualizar.
  - `process_manager.is_installer_process_name`: AI Boost excluye instaladores.
  - La copia de archivos del instalador (miles de `.js` en apps Electron, ~15 ms c/u por el antivirus) es igual que en la actualizacion propia de la app; esa la hace en segundo plano.
- **Verificacion:** 167/167 pruebas (`tests/test_v064_upgrade_reliability.py`, 9) y prueba real: Antigravity IDE 2.7.0 -> 2.8.0 desde la App.

## Cambios Consolidados v0.6.3 (21/11/2026, Claude Code)

- **ULTIMO USO preciso (`core/usage_telemetry.py`):** auditado contra el registro real del equipo.
  - Antes, cualquier proceso vivo marcaba "Hoy" (21 apps falsas: Bitdefender, Lenovo, WebView2, OneDrive). Ahora solo cuentan los procesos con ventana principal visible (`visible_window_pids`, EnumWindows).
  - Nueva fuente `HKCU\...\Search\JumplistData` (sin UAC, mas fresca que UserAssist).
  - Los AUMID de navegador por perfil (`Chrome.UserData.Profile1`, `MSEdge.x.Default`) cuentan como el navegador; WebView2 se ignora.
  - Se descartan los segmentos numericos de los AUMID (`Microsoft.Office.EXCEL.EXE.15` -> `excel`).
  - Los accesos `.lnk` de UserAssist se resuelven a su `.exe` (`resolve_lnk_target`, lector MS-SHLLINK sin pywin32); se agrego el KNOWNFOLDERID de accesos anclados `{9E3995AB-...}`.
  - Alias de suites (`_SUITE_ALIASES`: Microsoft 365/Office, Stata, Power BI, Zoom, Teams, WhatsApp). Complementos e instaladores no heredan la fecha (`_COMPONENT_MARKERS`).
  - BAM y Prefetch solo se leen como administrador; sin UAC dan 0 claves.
  - "Sin registro" es honesto: Windows no guardo ninguna apertura.
- **Actualizar apps desde la App (`apps/app_manager.py`, `ui/views/apps_view.py`):**
  - Seleccion multiple (Ctrl/Mayus) con "Actualizar seleccionadas" y nuevo "Actualizar todas" (`upgrade_apps_winget`: una por una, cancelable entre apps).
  - `bulk_upgrade_skip_reason` excluye del lote las apps protegidas, los entornos de desarrollo (Python, Anaconda, R, Rtools, Node, Java, .NET, VC++, WSL, PHP) y los saltos de version mayor; esas se actualizan a mano, con advertencia.
- **Vigia diario (`core/daily_watch.py`, `main_window._maybe_run_daily_watch`):**
  - Revisa cada 5 min si paso un horario (`SREPolicyConfig.daily_watch_hours`, por defecto 9/14/19); si el equipo estaba suspendido, avisa al volver, una vez por horario.
  - Solo lectura: consulta winget y temporales seguros (desde 300 MB).
  - Entrega un aviso en la campana por cada hallazgo y un globo de Windows SIEMPRE; al hacer clic, abre la pestana correspondiente (`tray.on_watch_clicked`).
  - No repite el mismo resumen antes de 20 h (`daily_watch_last_signature`).
  - El asesor de 15 min ya no escanea temporales (evita avisos duplicados).
  - Bajo pytest no se ejecuta (`PYTEST_CURRENT_TEST`).
- **Pruebas:** `tests/test_v063_usage_updates_watch.py` (10).
- **Verificacion:** 158/158 pruebas aprobadas; publicado como release v0.6.3 tras el "si" del propietario.

## Cambios Consolidados v0.6.2

- **Tablas/arboles redimensionables y scroll horizontal (`widgets.py`, `theme.py`, `sre_policy.py`):** todas las 10 tablas/arboles (`Aplicaciones`, `Inicio Windows`, 5 sub-modos + arboles/formatos de `Almacenamiento`, `Procesos` + MCP, `Termica/BIOS`, `Resumen`) usan `configure_interactive_columns` (`Interactive`, `stretchLastSection(False)`, anchos minimos por `QFontMetrics`, doble clic auto-fit, tooltips de celda completa, persistencia en `SREPolicyConfig.table_column_widths`) y scrollbar horizontal `0px` (`ScrollPerPixel`), con `setSortIndicator(-1, AscendingOrder)` en `configure_sortable_table` para respetar orden prioritario (`ACTUALIZAR`/`DESACTIVAR` arriba).
- **Telemetria `ULTIMO USO` sin UAC y `winget` automatico (`usage_telemetry.py`, `app_manager.py`, `apps_view.py`):** lectura de `HKCU\...\Explorer\UserAssist` (ROT13 + KNOWNFOLDERIDs + AUMIDs) sin UAC; eliminacion de `_probe_dir_last_exe_ts` (`st_atime` generaba falsos `"Hoy"` tras antivirus), distincion `"++"`, bloqueo de tokens genericos y respaldo `Inst. YYYY-MM-DD`/`Sin registro`; escaneo de aplicaciones encadena `check_app_updates_winget` con estados honestos (`REVISANDO` -> `ACTUALIZAR`/`AL DIA`/`SIN REVISAR`).
- **Correccion critica de "Elevar Admin" (`win32_bridge.py`, `main_window.py`, `app.py`, `single_instance.py`):** `run_elevated_command(..., track=False, directory=...)` protege el PID nuevo via `protect_child_pid()` y cierra el handle sin meterlo en `_TRACKED_CHILDREN`, impidiendo que `terminate_app_child_processes()` mate la instancia elevada con `TerminateProcess` al salir; `_kernel32_proc()` fija `argtypes`/`restype` 64-bit, `SingleInstanceLock` espera 30 s en `--elevated-relaunch` y controla `ERROR_ACCESS_DENIED (5)`.
- **Verificacion:** `148/148` pruebas aprobadas (`tests/test_v062_tables_and_usage.py`) + capturas reales claras/oscuras en PC.

## Cambios Consolidados v0.6.1

Consolidado entre Claude Code y Antigravity (aprobado por el propietario y empaquetado para release):
- **Icono barra de tareas y bandeja:** `app.py` fija `SetCurrentProcessExplicitAppUserModelID("TRODAI.WinOptiAI")` y usa `winoptiai.ico` como icono de ventana; `installer.iss` agrega `AppUserModelID`, `ChangesAssociations=yes` y `ie4uinit.exe -show`; tooltip de bandeja en `system_tray.py` reducido a `"WinOptiAI"`.
- **Medidores de Salud (`history_charts.SystemGaugesWidget` + `overview_view._fourth_gauge`):** `css_qcolor()` traduce `rgba(...)` evitando fondo negro en modo claro; cuadricula 2x2 adaptable con 4.o medidor (`TEMP. CPU` o `MEM. VIRTUAL`) y detalle compacto bajo cada etiqueta.
- **Graficas sin recorte de ejes ni leyendas (`history_charts.py`):** `TimeSeriesChart` y `FreedSpaceChart` calculan dinamicamente `_layout_metrics(fm)` segun el ancho real del eje Y (`43.91 GB`, `128 GB`) y alto del eje X; `_FreedLegend` ajusta altura `max(22, fm.height()+6)`; `HistoryPanel.legend_lbl` pasa a linea propia (`Caption`) para evitar que `summary_lbl` comprima la grafica a `980x650`.
- **Jerarquia tipografica y badges sin recorte (`theme.py`, `widgets.py`, `i18n.py`, vistas y dialogos):** pesos estrictos `700`/`500`/`400`/`300` (cero `600`/`DemiBold`); todos los textos de prosa/resumenes/banners/guias usan `CardTitle`/`BodyText` en `Space Grotesk` (reservando `MonoValue` para cifras KPI, rutas y logs); `StatusTag` fija `QSizePolicy.Fixed` y tarjetas KPI usan `14px` compacto + titulos breves (`RAM`, `Disco C:`, `CPU / Temp`, `SRE Auto`).
- **Tour Guiado de 7 pasos y Prueba Rapida (`tour_dialog.py`, `onboarding_check.py`):** actualizado para recorrer las 6 pestanas reales (`0..5`, incluyendo Aplicaciones `winget`, Inicio Inteligente, Treemap moderno opaco, semaforos/anillos 2x2 y columna `ULTIMO USO`) y sumar una 6.a verificacion (`Aplicaciones e Inicio de Windows`) en la Prueba Rapida.
- **Intercambio minimalista TopBar / Barra lateral (`main_window.py`, `theme.py`):** boton de tema (`TopUtilityBtn`, `30x28`, fondo transparente) e idioma (`TopLangCombo`, `52x28`) arriba a la derecha junto a la campana; `admin_tag` (`MODO ESTANDAR` / `ADMIN UAC`) y `uac_btn` (`Elevar Admin`) al pie de `Sidebar`.
- **Verificacion:** capturas reales (Resumen claro/oscuro `980x650` y `1200x760` + pasos 5 y 6 del Tour) inspeccionadas sin recortes; suite completa `144/144` pruebas aprobadas (`uv run --no-sync pytest -v`, incluyendo `tests/test_v061_ui_polish.py`, `tests/test_v060_features.py` y `tests/test_v0511_features.py`).

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
- Version unica en `VERSION` (actualmente `0.6.5`), sincronizada con `pyproject.toml`, `packaging/installer.iss`, `tests/test_sre_and_hardware.py` y `CHANGELOG.md`.
- En Windows con `gh release create`, escribir notas en archivo temporal y pasar `--notes-file`.
- Usar commits semanticos descriptivos en espanol (`feat(core): ...`, `fix(ui): ...`, `docs: ...`).
- Adjuntar `git notes` tecnicas con contexto de verificacion a los commits principales (`git log --show-notes`, `git push origin main "refs/notes/*"`).
