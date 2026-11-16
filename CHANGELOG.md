# Registro de Cambios (CHANGELOG)

Todos los cambios notables de **WinOptiAI** se documentan en este archivo siguiendo [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/) y [Semantic Versioning](https://semver.org/lang/es/).

## [0.5.1] - 2026-11-16

### Corregido (P0)
- **Crash nativo `0xc0000005` en `shiboken6.abi3.dll` al usar "Acciones Automaticas" (`thermal_bios_view.py`):**
  - El slot `clicked` de un `QPushButton` incrustado con `setCellWidget` reconstruia sincronamente la tabla (`setRowCount`), y `backup_power_scheme()` + `execute_audit_action()` (UAC / `ShellExecuteW` / PowerShell) se ejecutaban en el hilo UI, bombeando mensajes de forma reentrante dentro del slot.
  - Ahora respaldo + accion corren en `run_async` (QThreadPool); las escrituras de configuracion y `audit.jsonl` quedan en el hilo UI; el re-render se difiere y agrupa con `QTimer.singleShot(0, ...)`; los botones viejos se desconectan y retiran con `removeCellWidget` (`deleteLater`); doble clic ignorado mientras la accion esta en curso.
  - Aviso explicito cuando `CHKDSK` / `DISM` / `SFC` / WinSxS / Defrag / TRIM siguen corriendo en una consola elevada desacoplada.
  - `detect_active_servicing_processes()` (`bios_auditor.py`): si ya hay un `Dism.exe` / `DismHost.exe` / `sfc.exe` activo, WinOptiAI no encola otra accion `DISM + SFC` ni `WinSxS` y lo indica al usuario.
- **Blindaje general (`main_window.py`, `notifications_drawer.py`, `win32_bridge.py`):**
  - Senales de `AsyncTask` conectadas con `Qt.QueuedConnection` explicita y workers finalizados retenidos un ciclo del event loop antes de liberarse.
  - Re-renders del cajon de notificaciones disparados desde botones hijos diferidos con `QTimer.singleShot(0, ...)`; widgets retirados con `hide()` + `deleteLater()`.
  - `run_elevated_command()` inicializa COM (STA) en el hilo llamador, requisito de `ShellExecuteW` fuera del hilo principal.

### Agregado
- **Detector de cierres inesperados y telemetria post-mortem local (`core/crash_guard.py`, `app.py`, `main_window.py`, `dialogs/crash_report_dialog.py`):**
  - `faulthandler` (todos los hilos) + `sys.excepthook` + `threading.excepthook` + `qInstallMessageHandler` escriben en `%LOCALAPPDATA%\WinOptiAI\crash.log` (rotacion a 1 MB) con fecha, version, traceback y ultimos eventos.
  - Marcador `session_lock.json` (PID, version, inicio, latido 60 s, `clean_exit`) marcado limpio en `closeEvent`, salida desde bandeja y `aboutToQuit`.
  - Si la sesion previa no cerro limpiamente: evento en `audit.jsonl`, notificacion `ERROR` prioritaria en la campanita, consulta de solo lectura de eventos `APPCRASH` (ID 1000) de `WinOptiAI.exe` y boton `Diagnostico` en Notificaciones y Acerca de para ver, abrir o copiar el informe. Sin envio a servicios externos.
- **Casilla tri-estado "Seleccionar todo" en Almacenamiento (`storage_view.py`, `i18n.py`, `theme.py`):**
  - Disponible en `Temporales`, `Duplicados`, `Huerfanos`, `Cuarentena` y `OneDrive`; oculta en `Arbol y Formatos`; sincronizada con la seleccion manual y el cambio de sub-modo; muestra `N de M seleccionados | tamano`.
  - El borrado sigue pasando por `QuarantineVault` / `safety_guard.py` sin cambios.

## [0.5.0] - 2026-11-16

### Agregado y Mejorado (Auditoria Experta v0.5.0)
- **Control Cooperativo de Procesos y Sesiones Retomables (`core/task_control.py`, `workers.py`, `main_window.py`, `notifications_drawer.py`, `junk_scanner.py`):**
  - Nuevos controles globales en barra superior y panel de Tareas: **`Pausar` / `Reanudar`**, **`Guardar Pausa`** (persiste el progreso pendiente en `%LOCALAPPDATA%\WinOptiAI\sessions\<id>.json` tras asegurar en Cuarentena lo ya procesado) y **`Cancelar`**.
  - Nuevo boton **`Retomar Sesion (N)`** y lista interactiva de sesiones guardadas para continuar limpiezas largas tras cerrar o reiniciar el equipo (`resume_junk_session()`).
  - Cancelacion cooperativa tambien integrada en escaneo de temporales, duplicados BLAKE3 (`duplicate_finder.py`), arbol de almacenamiento (`tree_analyzer.py`) y OneDrive local (`onedrive_optimizer.py`).
- **Diagnostico Profundo de Disco S.M.A.R.T., Eventos NTFS/WHEA e Integridad OS (`thermal_bios/bios_auditor.py`, `thermal_bios_view.py`):**
  - Telemetria real S.M.A.R.T. NVMe/SSD (`Wear`, `Temperature`, `ReadErrorsTotal`, `WriteErrorsTotal`, `PowerOnHours`) y conteo de errores criticos `Disk` / `Ntfs` / `stornvme` / `WHEA-Logger` de los ultimos 14 dias.
  - Remediaciones en 1 clic con elevacion UAC: **`CHKDSK C: /scan`**, **`DISM /RestoreHealth + sfc /scannow`** y **`DISM StartComponentCleanup`** (limpieza de WinSxS).
  - Nuevas rutas profundas de limpieza (`junk_scanner.py`, `safety_guard.py`): `Windows\SoftwareDistribution\Download`, `DeliveryOptimization`, `VS Code CachedData` y bloqueos temporales `HuggingFace .locks`.
- **Auditoria UEFI/OEM, Seguridad Hardware y Verificacion Termica (`thermal_bios/`, `bios_auditor.py`):**
  - Alerta automatica si el BIOS tiene mas de 2 anos de antiguedad con deteccion multi-OEM (`Lenovo Vantage`, `Dell Command Update`, `HP Support Assistant`, `MyASUS`).
  - Auditoria de postura de seguridad: **TPM 2.0**, **BitLocker**, **HVCI / Integridad de memoria (Core Isolation)** y **Inicio Rapido (`HiberbootEnabled`)** con accion 1-clic `disable_fast_startup`.
  - Lectura de verificacion post-aplicacion via `powercfg /q` en `apply_thermal_profile()`.
- **Proteccion Activa en `AI Boost`, CPU% en Vivo y Retencion 30d (`process_manager.py`, `win32_bridge.py`, `safety_guard.py`, `installer.iss`):**
  - `run_ai_boost()` protege ahora su propio PID, la ventana en primer plano activa (`get_foreground_pid()`) y agentes IA/IDE (`AI_FOREGROUND_AGENTS`).
  - `list_top_processes()` mantiene cache de handles `psutil.Process` para reportar consumo real `% CPU` por proceso.
  - Expiracion automatica en arranque (`_phase2_warmup`) de lotes `Basura:*` en Cuarentena con mas de 30 dias (`purge_expired_items()`).
  - Escudo `[Code] PrepareToInstall` en Inno Setup 6 para detectar instancias elevadas de `WinOptiAI.exe` antes de sobrescribir binarios y escrituras atomicas compartidas (`atomic_write_text`).

## [0.4.2] - 2026-11-16

### Corregido y Optimizado
- **Eliminacion del Cuello de Botella Restart Manager en Limpieza Masiva (`junk_scanner.py`, `workers.py`):**
  - Se detecto que `_filter_unlocked_binary()` sobre 150,000+ archivos temporales ejecutaba miles de sesiones COM/RPC a `Rstrtmgr.dll` antes de mover el primer archivo y quedaba clavado en `5%` sin activar la ETA.
  - Para directorios masivos (`> 400` archivos) ahora usa deteccion atomica nativa NTFS (`WinError 32` / `PermissionError` en microsegundos al intentar `os.replace`), reusa el indice escaneado reciente (`_cached_eligible`), excluye la propia carpeta temporal `_MEIPASS` activa de PyInstaller, poda subcarpetas temporales vacias y pondera el `%` por cantidad real de archivos (`6% -> 100%`) para mostrar tiempo restante real desde los primeros 2 segundos.
- **Oferta Directa de Elevacion Admin UAC en Limpieza Profunda (`storage_view.py`):** si la limpieza seleccionada incluye carpetas del sistema (`Windows\Temp`, `Minidump`, `WER`) en modo estandar, pregunta en 1 clic si se desea elevar por UAC o limpiar de inmediato las rutas de usuario.

## [0.4.1] - 2026-11-16

### Corregido
- **Relanzamiento Limpio PyInstaller en Auto-Actualizador y UAC (`updater.py`, `win32_bridge.py`):** al actualizar o elevar desde `--onefile`, el subproceso heredaba `_MEIPASS2` y `_PYI_APPLICATION_HOME_DIR` del proceso saliente ya borrado, provocando `Failed to load Python DLL ...\_MEI...\python311.dll` al reabrir. Ahora el script puente y `ShellExecuteW` limpian explícitamente todas las variables `_MEIPASS*` / `_PYI_*` para garantizar un arranque limpio en nueva carpeta temporal.

## [0.4.0] - 2026-11-16

### Agregado y Corregido
- **Optimizador Hibrido OneDrive Local + Nube (`onedrive_optimizer.py`, `storage_view.py`, `win32_bridge.py`):**
  - Nuevo 6to sub-modo **`OneDrive Nube`** dentro de Almacenamiento (ES/EN/PT en `i18n.py`).
  - **Modo Local (Files On-Demand):** detecta carpetas sincronizadas (`OneDriveCommercial` / `OneDrive`), protege automaticamente repositorios de codigo (`.git` / `.venv` / `node_modules`) y convierte archivos pesados/inactivos en placeholders `"Solo en la nube"` via Win32 `SetFileAttributesW` (`+U -P`) sin borrar nada.
  - **Modo Nube (Microsoft Graph OAuth 2.0 PKCE + Windows DPAPI):** soporta cuentas Personales (MSA) y Corporativas/Educativas (Entra ID) con Client ID configurable, tokens cifrados en disco con `CryptProtectData` (DPAPI), consulta de cuota `/me/drive`, deteccion de duplicados exactos sin descargas por `quickXorHash`/`sha256Hash`, exclusion de carpetas compartidas de terceros por defecto y envio seguro a la Papelera de OneDrive.
- **Auto-Actualizador Desacoplado Endurecido (`updater.py`):** reemplazado `timeout /t` (que fallaba silenciosamente sin consola por redireccion de stdin en procesos GUI) por espera real `ping -n` + `bridge.log` con deteccion de codigo de salida.
- **Guardado Atomico Resiliente (`safety_guard.py`):** reintentos breves ante bloqueos momentaneos de antivirus/indexador al reemplazar `manifest.json`.

## [0.3.3] - 2026-11-16

### Corregido y Optimizado
- **Limpieza Masiva de Temporales en Segundos (sin atasco al 5% ni esperas de horas) (`junk_scanner.py`, `safety_guard.py`):**
  - Se elimino la reescritura cuadratica $O(N^2)$ de `manifest.json` y el calculo redundante de SHA-256/Restart Manager archivo por archivo: ahora los temporales limpios se mueven en un unico lote reversible (`quarantine_batch_bundle`) con `os.replace` en NTFS y verificacion de bloqueos binaria divide-y-venceras (`_filter_unlocked_binary`), reduciendo decenas de miles de archivos de ~14 horas a segundos.
  - Se agrego barra de progreso real (`5% -> 100%`) y tiempo restante estimado realista (`AsyncTask.eta_label()`) en todas las operaciones de Almacenamiento (temporales, duplicados, autolimpiador, hardlinks NTFS, arbol de carpetas, huerfanos y boveda de cuarentena).
- **Depuracion y Vaciado de Boveda Cuarentena (`storage_view.py`, `safety_guard.py`):** nuevo boton **Depurar / Vaciar Boveda** con eliminacion por lote `O(N)`.
- **Escaneo Rapido de Disco, Procesos y Hardware Real (`win32_bridge.py`, `process_manager.py`, `bios_auditor.py`):**
  - `os.scandir` de una sola llamada con `st_file_attributes` en los 4 motores de disco.
  - `detect_orphan_ai_workers` optimizado de ~7 s a `< 0.2 s` evitando leer `cmdline()` de procesos del sistema.
  - Correccion del ordenamiento en `Get-PhysicalDisk` excluyendo discos virtuales (`Msft Virtual Disk`) para mostrar correctamente la unidad NVMe fisica (`KINGSTON SNV3S1000G`).

## [0.3.2] - 2026-11-16

### Mejorado y Corregido
- **Contraste de Iconos en Tema Claro y Oscuro (`main_window.py`, `theme.py`):** al iniciar la app se sincroniza inmediatamente `icon_inverted` e `explorer_icon` en todas las vistas, corrigiendo los iconos oscuros sobre botones primarios oscuros y el tono tenue del boton de Explorador en modo claro.
- **Trazos de Boceto a Lapiz y Papel Medio Arrugado de Libreta (`assets/icons/*.svg`, `widgets.py`):** iconos SVG redibujados con doble trazo y sombreado sutil de lapiz tecnico, textura procedural cacheada de papel medio arrugado con pliegues y fibras organicas, cuadricula de cuaderno con guias mayores cada 120 px y doble margen vertical de libreta.
- **Activacion de Animaciones del Sistema:** guia/soporte para mantener activos los efectos visuales de Windows 11 (`MinAnimate`, `TaskbarAnimations`, `ClientAreaAnimation`).

## [0.3.1] - 2026-11-16

### Corregido y Mejorado
- **Actualizador Desacoplado con Proceso Puente Independiente (`updater.py`, `about_updater_dialog.py`):** al actualizar desde PyInstaller `--onefile`, `ShellExecuteW` lanza `apply_update.cmd` completamente fuera del Job Object padre, termina `WinOptiAI.exe` si sigue activo (`taskkill /F /T`), ejecuta `WinOptiAI-Setup.exe /SP- /SILENT /CURRENTUSER` preservando la ruta de instalacion y reabre WinOptiAI automaticamente al finalizar.
- **Aviso de Tareas Activas y Barra de Progreso % en Actualizacion:** antes de actualizar, verifica tareas en ejecucion mostrando su nombre y `%`; durante la descarga muestra barra `0–100%` y MB descargados en tiempo real.

## [0.3.0] - 2026-11-16

### Agregado y Mejorado
- **Concurrencia RAM-Aware y Progreso % en Segundo Plano (`workers.py`, `main_window.py`):** ejecucion simultanea de hasta 4 tareas en segundo plano mientras la RAM libre sea >= `1.0 GB`, sin bloquear otras vistas/acciones y con porcentaje real (`0-100%`) por tarea.
- **Campana Moderna y Centro de Notificaciones (`notifications.py`, `notifications_drawer.py`):** boton campana SVG con contador de no leidas en la barra superior, panel desplegable con barras de progreso individuales, historial persistente de tareas/sugerencias y eliminacion individual o masiva manual.
- **Asesor Periodico de Baja Frecuencia (`PeriodicAdvisor`):** verifica cambios relevantes cada 15 min (con enfriamiento de 2 horas por categoria) sin saturar al usuario.
- **Estetica Papeleria / Cuaderno hecho a Lapiz (`widgets.py`, `theme.py`, `assets/icons/*.svg`):** fondo de papel cuadriculado (`NotebookCanvas`, 24px con linea de margen), trazos de boceto a lapiz en todos los iconos SVG y conmutador Claro/Oscuro minimalista con iconos de sol y luna (`sun.svg` / `moon.svg`).
- **Permisos UAC bajo Demanda (`main_window.py`, `junk_scanner.py`, `safety_guard.py`):** soporte para elevar a Administrador al limpiar residuos de Windows (`Windows\Temp`, `Minidump`, `WER\ReportArchive`) manteniendo intactas las listas blancas del sistema operativo.

## [0.2.2] - 2026-11-16

### Agregado y Corregido
- **Copias de seguridad previas automaticas (`PreOpBackupManager`):** antes de cada optimizacion termica/energia, AI Boost o limpieza de almacenamiento, WinOptiAI guarda un respaldo `.pow` del plan de energia activo o instantanea `snapshot.json` en `%LOCALAPPDATA%\WinOptiAI\Backups` y registra el respaldo en el historial.
- **Indicador explicito de reinicio y retiro de pendientes en Auditoria (`bios_auditor.py`, `thermal_bios_view.py`):** columna `REINICIO` en cada recomendacion (*NO (inmediato)* vs *SI (reinicia a UEFI / tras driver)*), confirmacion explicita antes de reiniciar a UEFI, eliminacion automatica de la lista de pendientes al ejecutarse y registro inmediato en el historial de operaciones.
- **Hora local sincronizada con Windows (`sre_policy.py`, `safety_guard.py`, `overview_view.py`):** todas las marcas de tiempo en registros, cuarentena, copias de seguridad e historial usan la hora local exacta del sistema.

## [0.2.1] - 2026-11-16

### Corregido
- **Conectividad HTTPS del Auto-Actualizador en binario compilado (`build_exe.py`, `updater.py`):** se priorizan las DLLs `libssl-3-x64.dll` y `libcrypto-3-x64.dll` propias de Python en PyInstaller (evitando colisiones con otras instalaciones en `PATH`) y se agrega respaldo nativo con `curl.exe` SChannel de Windows 11, ademas del mensaje claro *"No hay actualizacion disponible: ya tienes la version mas reciente"*.
- **Cierre limpio en actualizaciones (`installer.iss`, `about_updater_dialog.py`):** `PrepareToInstall` termina `WinOptiAI.exe` antes de sobrescribir archivos y el dialogo invoca `_quit_app()` al relanzar el instalador.

## [0.2.0] - 2026-11-16

### Agregado
- **Perfilador Universal Multi-Hardware (`bios_auditor.py`):** deteccion dinamica de CPU (Intel/AMD/ARM64), GPU (NVIDIA/AMD/Intel), tipo de disco (NVMe/SSD/HDD), RAM total con calibracion dinamica SRE y acciones automaticas 1-clic directamente desde la tabla de Auditoria.
- **Telemetria en Tiempo Real (`telemetry.py`):** lectura independiente de idioma via `pdh.dll` de frecuencia real (GHz), Turbo Boost (%), carga por nucleo y sensores termicos ACPI/NVMe (con lectura elevada UAC bajo demanda).
- **Vista Previa y Autolimpiador Inteligente de Duplicados (`storage_view.py`, `duplicate_finder.py`):** previsualizacion de imagenes, texto y binarios, selector automatico (*mas antiguo*, *mas reciente*, *ruta mas corta*, *fuera de Descargas*) y autolimpieza hacia Cuarentena.
- **Vista Jerarquica por Carpetas y Formatos (`tree_analyzer.py`):** arbol expandible de carpetas por peso real y desglose por extension/categoria con envio directo del archivo mas pesado a Cuarentena.
- **Acceso Directo al Explorador y Tablas Ordenables (`widgets.py`, `win32_bridge.py`):** ordenamiento numerico/alfabetico en todas las tablas y arboles, boton *Ver en Explorador*, doble clic y menu contextual para inspeccionar cualquier resultado antes de limpiar.
- **Temas Claro / Oscuro, Multi-Idioma e Instalador Multilingue (`theme.py`, `i18n.py`, `installer.iss`):** conmutador *Obsidian Acrylic* (oscuro) <-> *Alabaster Frost* (claro) manteniendo `0px`, soporte **ES / EN / PT** en la app e instalador Inno Setup 6.
- **Acerca de y Auto-Actualizador (`about_updater_dialog.py`, `updater.py`):** creditos de **Dairo (`dairo707-maker`)**, verificacion contra GitHub Releases y descarga/instalacion verificada por SHA-256.

## [0.1.0] - 2026-11-16

### Agregado
- **Puente nativo Win32 (`win32_bridge.py`):**
  - Deteccion de archivos OneDrive Cloud-Only (`GetFileAttributesW`) para evitar hidratacion involuntaria.
  - Verificacion de bloqueos de archivos en uso a nivel de kernel mediante Windows Restart Manager (`Rstrtmgr.dll`).
  - Activacion de modo eficiencia **EcoQoS** (`SetProcessInformation`) y compactacion segura de memoria (`EmptyWorkingSet`).
  - Creacion de enlaces duros NTFS (`CreateHardLinkW`) y envio a Papelera nativa (`SHFileOperationW`).
  - Integracion DWM Acrylic con esquinas rectas `0px` (`DWMWCP_DONOTROUND`) en Windows 11.
- **Seguridad y Politica Hibrida SRE (`safety_guard.py`, `sre_policy.py`):**
  - Listas blancas inmutables de rutas del sistema y procesos criticos/antivirus (incluyendo Bitdefender y OneDrive).
  - **Boveda de Cuarentena** transaccional con validacion SHA-256 y restauracion 1-clic.
  - Guardia SRE automatico con umbral `< 1.8 GB` de RAM libre e histeresis de `300 s`, con auditoria `audit.jsonl`.
- **Motor de Almacenamiento (`storage/`):**
  - Escaneo de temporales y caches (`Temp`, `D3DSCache`, `uv`, `pip`, `npm`, `NuGet`, caches web).
  - Buscador de duplicados **BLAKE3 en 4 etapas** con soporte de Cuarentena y Hardlinks NTFS.
  - Detector de archivos sueltos/huerfanos y residuos de aplicaciones desinstaladas.
- **Optimizacion para IA Agentica y Termica (`ai_optimizer/`, `thermal_bios/`):**
  - Accion **AI Boost**, proteccion de agentes activos (`Antigravity`, `Claude`, `Code`, `Ollama`) y cazador de workers MCP zombis.
  - Tres perfiles termicos oficiales via `powercfg` (*Frio / Silencioso*, *Equilibrado Inteligente*, *IA Local Maxima*).
  - Auditoria SMBIOS/WMI de BIOS, driver GPU Intel Iris Xe, salud NVMe/TRIM y reinicio guiado a UEFI (`shutdown /r /fw`).
- **Interfaz Obsidian Acrylic y Empaquetado (`ui/`, `scripts/build_exe.py`, `packaging/`):**
  - UI minimalista `0px` con tipografia embebida **Instrument Sans + IBM Plex Mono** (OFL) e iconos **SVG** propios (cero emojis).
  - Icono ligero en System Tray y compilacion a `WinOptiAI-Portable.exe` y `WinOptiAI-Setup.exe` (asistente nativo Inno Setup 6 paso a paso con seleccion de modo de usuario/sistema, selector de directorio, tareas opcionales y desinstalador Windows).
  - Guia completa de instalacion paso a paso en `docs/INSTALL_GUIDE.md`.
