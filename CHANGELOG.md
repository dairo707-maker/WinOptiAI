# Registro de Cambios (CHANGELOG)

Todos los cambios notables de **WinOptiAI** se documentan en este archivo siguiendo [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/) y [Semantic Versioning](https://semver.org/lang/es/).

## [0.5.12] - 2026-11-17

### Corregido (Issue #1 de GitHub)
- **`RuntimeError: Internal C++ object (QPushButton) already deleted` al cerrar el Tour durante la Prueba Rapida (`tour_dialog.py`, `about_updater_dialog.py`):**
  - Capturado por el reporte de errores de `v0.5.11` (Issue `#1`): si el usuario cerraba el diálogo del Tour (`WA_DeleteOnClose`) antes de que terminara `run_new_pc_quick_check()` en `QThreadPool` (~3-9 s), el callback `_done()` intentaba habilitar `recheck_btn` ya eliminado en C++.
  - Protegidos todos los callbacks asincronos (`_on_check_progress`, `_done`, `_err` y actualización de `AboutUpdaterDialog`) con `shiboken6.isValid()` + bandera de cierre (`closeEvent`/`reject`) para ignorar actualizaciones sobre widgets ya liberados y guardar `onboarding_completed = True` aunque se cierre con `X`/`Esc`.

## [0.5.11] - 2026-11-17

### Agregado y Mejorado
- **Bandeja del Sistema Visible y Modos Sincronizados (`ui/system_tray.py`, `win32_bridge.py`, `main_window.py`):**
  - Icono geometrico multi-resolucion (`16/20/24/32 px`) con placa de alto contraste adaptable automaticamente a barra de tareas clara u oscura (`SystemUsesLightTheme`), evitando que se vea lavado o casi transparente.
  - Menu contextual muestra el estado/proceso en curso, checks exclusivos (`QActionGroup`) en el modo termico activo (`Perfil Termico: Frio/Equilibrado/IA Maxima`) e interruptores sincronizados para **`Guardia SRE Automatico`** y **`Tema Claro (Alabaster)`**.
- **Tour Rapido Guiado y Prueba Rapida de Equipo Nuevo (`core/onboarding_check.py`, `ui/dialogs/tour_dialog.py`, `sre_policy.py`):**
  - Tour interactivo de 5 pasos en tarjeta `0px` que recorre en vivo las pestanas principales en el primer arranque y se puede reabrir desde la barra lateral o `Acerca de` (`Tour y Prueba Rapida`).
  - El Paso 5 ejecuta una prueba rapida segura de solo lectura (~3-5 s en `QThreadPool`) que verifica CPU/RAM + calibracion SRE, disco/S.M.A.R.T./eventos 14d, sensores `pdh.dll` + plan de energia, BIOS/OEM/seguridad/reinicio pendiente (`has_windows_reboot_pending`), OneDrive local y Boveda.
- **Branding Propio del Instalador y Soporte SmartScreen (`scripts/build_exe.py`, `packaging/installer.iss`, `docs/INSTALL_GUIDE.md`):**
  - Nuevo icono geometrico `winoptiai.ico` con mayor contraste + generacion automatica de banners `wizard_large.bmp` (`164x314`) y `wizard_small.bmp` (`55x58`) en estilo `0px` Obsidian Acrylic para reemplazar la caja/disco azul generica de Inno Setup 6.
  - Soporte opcional de firma Authenticode (`WINOPTIAI_SIGN_PFX` / `WINOPTIAI_SIGN_SHA1` + `signtool.exe`) y guia clara en 1 clic frente al aviso *"Editor desconocido"* de SmartScreen.

## [0.5.10] - 2026-11-17

### Corregido
- **Falsas alarmas de "interfaz bloqueada" tras suspender el equipo:** el vigilante de bloqueos contaba el tiempo en que el portatil estuvo dormido y escribia en `crash.log` bloqueos de 482 s, 2 h y 5 h que no existieron. Ahora reconoce la suspension y solo registra bloqueos reales.

### Verificado
- Cierre total en la app instalada (v0.5.9): al salir no queda ningun proceso de WinOptiAI ni consolas iniciadas por la app, y la sesion se marca como cerrada correctamente.

## [0.5.9] - 2026-11-17

### Corregido (P0 - incidente 17/11: Autolimpiar duplicados sobre todo el disco)
- **Duplicados ya no toca programas.** La autolimpieza de la v0.5.7 movio a Cuarentena 164.273 copias identicas que no sobraban (bibliotecas de Python de uv, Anaconda y Python 3.13, DLL de Qt, `C:\Drivers`, datos de Teams, Zoom y navegadores), dejando esas instalaciones rotas. Todo se restauro (164.096 archivos; 176 que el propio programa ya habia recreado quedaron en la Boveda; 1 de Lenovo Vantage requiere administrador). Desde ahora Duplicados no recorre carpetas de programas, entornos, sistema ni configuracion (`AppData`, `Program Files`, `ProgramData`, `C:\Drivers`, `site-packages`, `.venv`, `node_modules`, Anaconda, carpetas ocultas, `_MEI` de PyInstaller) ni carpetas con marcas de instalacion (`.exe` con `.dll`, `pyvenv.cfg`, `conda-meta`).
- **Carpetas copiadas protegidas:** si dos carpetas tienen la misma estructura (muchos archivos identicos), sus grupos se marcan "PROTEGIDO: carpeta copiada" y nunca se proponen; siempre se conserva al menos una copia del usuario.
- **Autolimpiar pide confirmacion** con un resumen (copias, tamano, carpetas con mas copias y lo protegido) y ahora se puede **cancelar**.
- **Cerrar la app cierra todo:** antes se esperaban 3 s y la tarea seguia sin ventana (la autolimpieza siguio 12 minutos tras "Salir"). Ahora se cancelan todas las tareas en un punto seguro (lo hecho queda registrado), se cierran las consolas y procesos que inicio la app (PowerShell, DISM, CHKDSK, TRIM...) y, si algo siguiera activo, el proceso termina por completo. Se respetan el navegador, el Explorador, Configuracion y el actualizador. Si hay una reparacion DISM/SFC/CHKDSK en curso, se pide confirmacion.
- **Lo enviado a Cuarentena no reaparece:** la Boveda y los datos de la app quedan fuera de todos los escaneos (antes Arbol mostraba archivos de la propia Boveda).

### Agregado
- **Cuarentena instantanea:** tecla Supr, clic derecho, icono de caneca en cada fila o arrastrar archivos desde el Explorador a la pestana "Boveda Cuarentena". Sin abrir un proceso: suena la Papelera de Windows, la fila se desvanece, la pestana muestra el contador y aparece "Deshacer" durante unos segundos.
- **Sin reescanear tras cada accion:** lo movido se quita de la lista (Duplicados, Arbol, Huerfanos, Temporales, Hardlink).
- **Microprocesos:** la Boveda registra por lotes (cada 50 elementos; los lotes masivos de temporales cada 500), Duplicados recuerda las huellas BLAKE3 ya calculadas (`hash_cache.sqlite`) y "Guardar Pausa" funciona tambien en Duplicados y Arbol ("Retomar Sesion" los relanza sin repetir lo calculado).
- **Restauracion masiva** (`restore_items_bulk`) y copia de seguridad previa COMPLETA de las autolimpiezas (`snapshot_full.jsonl`).
- Animaciones sobrias (filas, aviso, contador de la Boveda, acercamiento en el mapa) que respetan "Mostrar animaciones en Windows".
- `SECURITY.md`: politica de seguridad y como reportar vulnerabilidades de forma privada.

## [0.5.8] - 2026-11-17

### Agregado
- **Monitoreo grafico con historial en Resumen:** nuevo panel "Monitoreo e historial" con tres pestanas.
  - *Historial RAM y CPU:* graficos de las ultimas 24 h o 7 dias con la RAM libre (y la linea del umbral SRE calibrado) y el uso de CPU. Sobre la misma linea de tiempo se marcan los eventos del registro: **B** AI Boost, **L** limpiezas, **D** depuraciones de Cuarentena y **E** informes de error. Al pasar el cursor se ven los valores de ese minuto (RAM, CPU, temperatura, disco libre y RAM de la propia app) o el detalle del evento. Un resumen indica la RAM libre minima, la CPU promedio, el porcentaje del tiempo bajo el umbral y cuantos AI Boost hubo.
  - *Espacio liberado:* area acumulada del espacio en disco que reporto liberar cada limpieza, por tipo (temporales, duplicados, Cuarentena y OneDrive), con totales historicos y de los ultimos 7 dias. AI Boost no se suma aqui porque libera RAM, no disco.
  - *Registro de operaciones:* la tabla de siempre.
- **Historial local y acotado (`metrics.sqlite`):** un punto por minuto (promedio de las lecturas de 2 s) mientras la app esta abierta, tambien minimizada en la bandeja. Se guardan como maximo 7 dias (~10 000 filas) y todas las lecturas y escrituras ocurren fuera del hilo grafico. Graficos dibujados con QPainter propio: monocromo, lineas de 1 px, esquinas rectas.

### Corregido
- **Boveda: archivo suelto "bloqueado" que no se borraba.** Los elementos de un solo archivo (por ejemplo, un `.rar` enviado a Cuarentena desde Arbol) se trataban como carpeta al depurar: nunca se eliminaban, se informaban como "abiertos por otro programa" y su tamano quedaba en 0. Ahora se eliminan normalmente.
- **Eventos duplicados en el registro (AI Boost repetido el 16/11 a las 22:45:35):** habia dos copias de WinOptiAI abiertas a la vez; cada una detecto la presion de RAM y ejecuto y registro su propio AI Boost (y ambas se pisaban el archivo de notificaciones). Ahora la app es de **instancia unica**: si se abre de nuevo, la ventana ya abierta pasa al frente. El relanzamiento como Administrador espera a que la copia anterior cierre. Ademas, el registro descarta una linea identica a la anterior escrita hace menos de 2 s, y los graficos cuentan una sola vez los duplicados ya guardados.

### Cambiado (interfaz)
- Tarjetas de metricas de Resumen mas compactas y vista desplazable, para que los graficos conserven una altura legible en la ventana minima (980x650).

## [0.5.7] - 2026-11-17

### Corregido
- **"Whoops, something went wrong!" al enviar un informe a GitHub.** El informe viajaba en la direccion web (hasta 7.600 caracteres); sin sesion iniciada, GitHub redirige al inicio de sesion repitiendo esa direccion y con ~5.900 caracteres responde error 500 (reproducido el 17/11). Ahora la direccion lleva un resumen de hasta 3.000 caracteres, el informe completo queda en el portapapeles y en `%LOCALAPPDATA%\WinOptiAI\reports`, y un aviso explica los pasos (iniciar sesion, pegar con Ctrl+V, pulsar Create).
- **"Guardar Pausa" solo donde funciona:** unicamente la limpieza de temporales (y su reanudacion) guarda un punto exacto para retomar. En las demas tareas el boton no hacia nada y la tarea seguia corriendo; ahora solo aparece cuando la tarea lo admite (barra superior y centro de notificaciones).

## [0.5.6] - 2026-11-17

### Cambiado (interfaz)
- **Botones nunca recortados:** auditoria automatica de todas las vistas y dialogos en modo oscuro y claro (1200x760 y ventana minima 980x650) encontro 184 casos en 14 botones. Corregidos con filas que pasan a una segunda linea (pestanas de Almacenamiento, acciones de Acerca de y de Termica), botones adaptativos en la barra superior (texto largo o corto segun el espacio, con el texto completo en el tooltip), dialogos redimensionables en lugar de tamano fijo y subtitulos con ajuste de linea. Una prueba de regresion recorre todas las vistas en ambos temas.
- **Acciones de cada pestana con color propio:** restaurar/restablecer en salvia, mover a Cuarentena/Papelera/hardlink en ambar y eliminar definitivo/cerrar procesos en oxido (tonos apagados de la paleta). Las pestanas de modo tienen un estilo de pestana distinto (subrayado al activarse).
- **Panel superior con bordes semirredondos** (resto de la interfaz sigue con esquinas rectas).
- Barra lateral algo mas ancha para "Acerca de y Actualizaciones"; tarjetas de perfil termico con titulo y etiqueta apilados; "Autolimpiar" de Duplicados deja de competir con la accion principal.

## [0.5.5] - 2026-11-16

### Corregido
- **OneDrive Nube: error `AADSTS50011` al iniciar sesion.** La app enviaba `http://localhost:<puerto>/callback` y Microsoft lo rechazaba si el registro tenia `http://localhost` (Entra ID ignora el puerto pero compara la ruta). Ahora usa `http://localhost:<puerto>`, que coincide con el registro indicado en la guia; la guia del dialogo lo aclara.
- **Error al guardar notificaciones simultaneas:** dos avisos a la vez (p. ej. AI Boost automatico) compartian el archivo temporal `notifications.tmp` y el segundo fallaba con `FileNotFoundError`, mostrando el aviso de error. Cada escritura atomica usa ahora un temporal unico.

## [0.5.4] - 2026-11-16

### Agregado
- **Mapa jerarquico (treemap) en Arbol y Formatos (`ui/treemap.py`):** bloques proporcionales al peso de cada carpeta, con sus subcarpetas visibles dentro; clic para entrar, "Subir" para volver, doble clic o menu para abrir en el Explorador. Estilo monocromo con lineas de 1 px y bordes rectos.
- **Pestana "Archivos mas pesados":** top 100 del analisis o agrupado por extension (desplegable, hasta 30 archivos por extension), filtro por tipo (Video, Documentos, Datos y Codigo, Correo, etc.) o por extension. Doble clic abre la carpeta en el Explorador con el archivo seleccionado; menu con "Copiar ruta" y "Enviar a Cuarentena" (con confirmacion).
- Nuevas categorias: Stata/SPSS/R/SIG, Outlook (`.pst`/`.ost`), maquinas virtuales, registros y temporales.

### Corregido
- **OneDrive ignorado en Arbol y Duplicados:** OneDrive marca sus carpetas con el atributo `UNPINNED` aunque esten en disco y los escaneos las trataban como "solo en la nube", omitiendo todo su contenido. Ahora solo se omiten carpetas que realmente requieren la nube para listarse; cada archivo se sigue protegiendo igual (nunca se hidrata).
- **Boveda de Cuarentena: elemento que no se podia borrar.** Los lotes con archivos de solo lectura o rutas de mas de 260 caracteres fallaban en silencio y quedaban a medias. La purga ahora quita el atributo de solo lectura, usa rutas largas, informa los archivos que siguen bloqueados (y conserva el registro con el tamano restante) y, al vaciar toda la Boveda, elimina tambien restos sin registro de purgas anteriores.

## [0.5.3] - 2026-11-16

### Corregido (P0 - "No responde" al terminar Arbol y Formatos)
- **Render del arbol sin limite (`storage_view.py`):** al terminar el analisis se creaban de golpe hasta 40 subcarpetas x 5 niveles (cientos de miles de items en un disco completo) y luego se ordenaban en el hilo GUI; la app llego a ~1,5 GB de RAM y Windows la cerro por bloqueo (Visor de eventos, Application Hang 1002, 16/11 19:03). Ahora la carga es perezosa: raiz + primer nivel, y cada carpeta carga sus hijos al expandirla; orden inicial por PESO.
- **Memoria del analizador (`tree_analyzer.py`):** solo se conservan las 60 subcarpetas mas pesadas por nivel (los totales siguen siendo completos) y el top-100 de archivos pesados usa un heap acotado.
- **Progreso congelado (`workers.py`):** el limitador de senales descartaba la ultima etapa ("Analizando DumpStack.log" quedaba fijo); ahora tambien emite cada vez que sube el porcentaje.

### Agregado
- **Aviso "WinOptiAI se cerro inesperadamente" con envio de informe:** tras cualquier cierre inesperado (fallo nativo, bloqueo terminado por Windows o fin de tarea) aparece al abrir la app un dialogo tipo Windows que pregunta si enviar el informe. Errores de Python no controlados muestran el aviso en el acto (una vez por error, maximo 3 por sesion).
- **Envio a GitHub Issues revisado por el usuario (`core/crash_reporter.py`):** el informe se anonimiza (usuario de Windows, equipo, organizacion de OneDrive, correos), se muestra completo en "Ver informe" y solo al pulsar "Enviar informe" se abre `github.com/dairo707-maker/WinOptiAI/issues/new` precargado; el texto completo queda en el portapapeles. Nada se envia automaticamente ni hay credenciales en el .exe. Tambien disponible en Diagnostico > "Enviar a GitHub".
- **Reinicio automatico tipo Office (`RegisterApplicationRestart`):** en el .exe, si Windows termina la app tras al menos 60 s abierta, la reabre con `--crash-restart` y el aviso sale de inmediato (no se reinicia por actualizaciones ni reinicios del sistema).
- **Vigilante de bloqueos (`crash_guard.py`):** si el hilo GUI no responde durante 8 s, vuelca las pilas de todos los hilos en `crash.log`; la consulta del Visor de eventos incluye ahora los bloqueos (ID 1002).

## [0.5.2] - 2026-11-16

### Corregido (P0 - causa raiz real del cierre `0xc0000005`)
- **Recursion infinita al ordenar tablas/arbol (`ui/widgets.py`):** `NumericTreeItem.__lt__` y `NumericTableItem.__lt__` llamaban a `super().__lt__()` cuando la columna no tenia valor numerico; en PySide6 eso vuelve a despachar al override de Python hasta desbordar la pila (`access violation` en `shiboken6.abi3.dll`, offset `0x2fa09`). Ocurria cada vez que terminaba un analisis de **Arbol y Formatos** (orden por la columna CARPETA) o al ordenar columnas mixtas. Capturado por `crash.log` (v0.5.1) el 16/11 a las 17:37 y reproducido de forma aislada. Ahora la comparacion de texto es propia y nunca invoca a Qt.

### Corregido (auditoria de codigo)
- **Seguridad de datos en Almacenamiento (`storage_view.py`):** un escaneo que terminaba mientras el usuario estaba en otro sub-modo dibujaba sus filas en la tabla compartida con indices de otra lista; una accion posterior (p. ej. "Enviar a Cuarentena" en Huerfanos) podia actuar sobre archivos equivocados. Cada `_render_*` solo dibuja si coincide el modo activo; los datos se conservan para cuando el usuario vuelva.
- Tras limpiar temporales o huerfanos ya no se relanza el analisis del modo *actual* (abria un selector de carpeta inesperado en Duplicados/Arbol); solo se reescanea el modo de origen.
- La carpeta de Duplicados y la de Arbol se fijan al lanzar cada analisis (`dup_root` / `tree_root`); antes un segundo analisis podia cambiar la carpeta del primero.
- **Hardlink NTFS (`duplicate_finder.py`):** re-verificacion de tamano + BLAKE3 de cada copia justo antes de enlazar (evita perder datos de un archivo editado despues del escaneo) y confirmacion explicita Si/No con advertencia en la interfaz.
- **Vista previa de duplicados:** lee solo los primeros 3500 bytes (antes cargaba el archivo completo en memoria en el hilo GUI), limita imagenes a 25 MB y nunca previsualiza archivos OneDrive solo-en-la-nube.
- **Rendimiento con muchos archivos (`workers.py`):** maximo ~10 senales de progreso por segundo por tarea (antes una por archivo, saturando el event loop).

### Cambiado
- Maximo **2 procesos de almacenamiento simultaneos** (escaneos/limpiezas); el tercero se rechaza con aviso claro.

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
