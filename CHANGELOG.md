# Registro de Cambios (CHANGELOG)

Todos los cambios notables de **WinOptiAI** se documentan en este archivo siguiendo [Keep a Changelog](https://keepachangelog.com/es-ES/1.0.0/) y [Semantic Versioning](https://semver.org/lang/es/).

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
