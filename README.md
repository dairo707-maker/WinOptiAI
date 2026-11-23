# WinOptiAI · by TRODAI

Gestor nativo de almacenamiento, optimizacion de procesos para IA agentica, administracion de aplicaciones (`winget`), inicio inteligente de Windows, telemetria en tiempo real, control termico y auditoria universal de hardware para **Windows 11**.

Creado por **Dairo (`dairo707-maker`)** · Repositorio oficial: `https://github.com/dairo707-maker/WinOptiAI`

> **Proyecto hermano para Android:** desarrollado en un repositorio privado separado (`dairo707-maker/WinOptiAI-Android`) para mantener independiente el canal de auto-actualizacion (`/releases/latest`) de Windows.

## Capacidades Principales

- **Resumen sin Scroll, Semaforos y Vigilancia Activa:**
  - Tarjetas KPI en una fila, cuadricula radial **2x2** (`RAM`, `Disco C:`, `CPU` y `TEMP. CPU` / `MEM. VIRTUAL`), historial de **24 h / 7 d**, grafico de espacio liberado y barra semaforo de subsistemas.
  - **Vigia diario (`daily_watch.py`):** revision de solo lectura en horarios configurables (`9`, `14` y `19 h`) que avisa sobre actualizaciones disponibles o temporales acumulados sin ejecutar cambios automaticos.
- **Almacenamiento con Seguridad Kernel:**
  - Proteccion estricta de marcadores **OneDrive Cloud-Only** (`GetFileAttributesW`) y exclusiones automaticas (`program_guard.py`) para no tocar entornos Python/Node/programas ni carpetas copiadas.
  - Verificacion de bloqueos con **Windows Restart Manager (`Rstrtmgr.dll`)** y fallback atomico NTFS en lotes `>400` archivos.
  - Deduplicador **BLAKE3 en 4 etapas** con **Vista Previa**, **Autolimpiador por Reglas**, **Hardlinks NTFS** y **Boveda de Cuarentena** transaccional SHA-256.
  - **Treemap jerarquico opaco**, arbol de carpetas perezoso, tabla de formatos y top-100 pesados, con columnas **`ULTIMO USO`** y anchos ajustables/persistentes con scroll horizontal en todas las tablas.
- **Administrador de Aplicaciones e Inicio Inteligente (`apps/`):**
  - Inventario combinado **Registro + `winget`** con **`ULTIMO USO`** real sin requerir UAC (`EnumWindows`, `JumplistData`, `UserAssist` + `.lnk`, aliases de suites), descarga directa **WinINet**, actualizaciones protegidas ante cierres de la app, seleccion multiple / **"Actualizar todas"**, iconos reales y desinstalacion segura con limpieza opcional de residuos hacia Cuarentena.
  - Analizador de **Inicio de Windows** (`Run`/`Startup`/`StartupApproved`) con sugerencias semaforo (`MANTENER`, `PAUSAR`, `DESACTIVAR`) 100% reversibles.
- **Optimizacion para IA Agentica, Termica y Hardware:**
  - Politica hibrida **SRE** calibrada dinamicamente segun RAM fisica (`1.2–4.0 GB`, histeresis `5 m`), **Windows 11 EcoQoS**, compactacion segura `EmptyWorkingSet` (excluyendo ventana activa, agentes IA e instaladores) y cazador de workers MCP zombis.
  - Monitoreo `pdh.dll`, sonda termica UAC segura sin archivos temporales, perfiles `powercfg`, S.M.A.R.T., TPM/BitLocker/HVCI y acciones `CHKDSK`/`DISM`/`SFC`/`WinSxS`.
- **Identidad TRODAI Dual Tema, Idiomas y Auto-Actualizador:**
  - Diseno `0px` **Obsidian Navy** (oscuro) y **Crisp White** (claro) con **Cyber Cyan / Governance Blue**, tipografias OFL **`Space Grotesk`** + **`JetBrains Mono`**, menús contextuales por seleccion, dialogos traducidos (**ES / EN / PT**) y auto-actualizador verificado con **SHA-256**.

## Instalacion (Paso a Paso) y Compilacion

### Opcion A — Instalador de Windows (Recomendado)
1. Descarga [`WinOptiAI-Setup.exe`](https://github.com/dairo707-maker/WinOptiAI/releases/latest) (o generarlo localmente en `dist/WinOptiAI-Setup.exe`).
2. **SmartScreen en PCs nuevos ("Editor desconocido"):** si aparece *"Windows protegio su PC"*, haz clic en **Mas informacion** -> **Ejecutar de todas formas** (o `Unblock-File .\WinOptiAI-Setup.exe` tras validar `SHA256SUMS.txt`).
3. Ejecuta `WinOptiAI-Setup.exe`: elige modo (**Solo para mi** o **Todos los usuarios**), directorio de instalacion y opciones de inicio.
4. Al abrir WinOptiAI por primera vez, el **Tour guiado de 7 pasos** ejecuta una **Prueba rapida** segura (~3–5 s) de 6 categorias para calibrar los umbrales del equipo.

### Opcion B — Compilacion desde Codigo Fuente
Requiere Python 3.11+, [uv](https://docs.astral.sh/uv/) e Inno Setup 6 (`winget install JRSoftware.InnoSetup`):

```powershell
uv sync --extra dev --link-mode=copy
uv run --no-sync pytest -v
uv run --no-sync python -m winoptiai.app
uv run --no-sync python scripts/build_exe.py
```

## Documentacion

- [Guia de Instalacion Paso a Paso](docs/INSTALL_GUIDE.md)
- [Arquitectura Tecnica](docs/ARCHITECTURE.md)
- [Protocolos de Seguridad y Sistema Operativo](docs/SECURITY_AND_OS_PROTOCOLS.md)
- [Guia Termica y BIOS Lenovo 82FE](docs/BIOS_AND_THERMAL_GUIDE_LENOVO_82FE.md)
- [Registro de Cambios (CHANGELOG)](CHANGELOG.md)
- [Contexto Multi-Agente](AGENTS.md) · [Referencia Maestra Claude/Agentes](CLAUDE.md)

## Licencia

Distribuido bajo licencia **MIT**. Ver [LICENSE](LICENSE).
