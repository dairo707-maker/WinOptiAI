# Registro de Cambios (CHANGELOG)

Todos los cambios notables de **WinOptiAI** se documentan en este archivo siguiendo [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/) y [Semantic Versioning](https://semver.org/lang/es/).

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
