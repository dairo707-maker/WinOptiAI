# WinOptiAI

Gestor nativo de almacenamiento, optimizacion de procesos para IA agentica, telemetria en tiempo real, control termico y auditoria universal de hardware para **Windows 11**.

Creado por **Dairo (`dairo707-maker`)** · Repositorio oficial: `https://github.com/dairo707-maker/WinOptiAI`

## Capacidades Principales

- **Almacenamiento con Seguridad Kernel:**
  - Proteccion estricta de marcadores **OneDrive Cloud-Only** (`GetFileAttributesW`) para evitar descargas accidentales.
  - Verificacion de bloqueos en tiempo real con **Windows Restart Manager (`Rstrtmgr.dll`)**.
  - Motor de deduplicacion **BLAKE3 en 4 etapas** con **Vista Previa**, **Autolimpiador por Reglas**, **Hardlinks NTFS** y **Boveda de Cuarentena** con restauracion SHA-256.
  - **Vista Jerarquica por Carpetas y Formatos**, tablas ordenables por columna y acceso **Ver en Explorador** en cada resultado.
- **Optimizacion para IA Agentica y Telemetria en Tiempo Real:**
  - Politica hibrida **SRE** calibrada automaticamente segun la RAM fisica del equipo (`1.2–4.0 GB` umbral, histeresis 5m).
  - Aplicacion nativa de **Windows 11 EcoQoS (Efficiency Mode)**, compactacion segura de Working Set (`EmptyWorkingSet`), visibilidad de tareas activas y cazador de workers MCP zombis.
  - Monitoreo en tiempo real via `pdh.dll` de frecuencia CPU (GHz), Turbo (%), carga por nucleo y sensores termicos ACPI/NVMe.
- **Perfilador Universal de Hardware, Temas y Auto-Actualizacion:**
  - Compatible con cualquier equipo Windows 11 (Intel/AMD/NVIDIA, portatiles y escritorios) con botones de accion automatica en la tabla de Auditoria.
  - Tema **Oscuro (Obsidian Acrylic)** y **Claro (Alabaster Frost)** de bordes rectos `0px`, idiomas **ES / EN / PT** en app e instalador Inno Setup 6, y **Auto-actualizador verificado con SHA-256** desde GitHub Releases.

## Instalacion (Paso a Paso) y Compilacion

### Opcion A — Instalador de Windows (Recomendado)
1. Ubica el instalador generado en [`dist/WinOptiAI-Setup.exe`](dist/WinOptiAI-Setup.exe) (o descargalo desde GitHub Releases).
2. Ejecuta `WinOptiAI-Setup.exe`: podras elegir el modo (**Solo para mi** o **Todos los usuarios**), **seleccionar el directorio de instalacion** con `Examinar...`, elegir accesos directos y habilitar el arranque minimizado opcional.
3. Consulta la guia detallada paso a paso (incluyendo verificacion SHA-256 y SmartScreen) en [Guia de Instalacion](docs/INSTALL_GUIDE.md).

### Opcion B — Compilacion desde Codigo Fuente
Requiere Python 3.11+, [uv](https://docs.astral.sh/uv/) e Inno Setup 6 (`winget install JRSoftware.InnoSetup`):

```powershell
uv sync --extra dev
uv run pytest -v
uv run python -m winoptiai.app
```

Para generar los ejecutables (`dist/WinOptiAI-Portable.exe` y `dist/WinOptiAI-Setup.exe`):

```powershell
uv run python scripts/build_exe.py
```

## Documentacion

- [Guia de Instalacion Paso a Paso](docs/INSTALL_GUIDE.md)
- [Arquitectura Tecnica](docs/ARCHITECTURE.md)
- [Protocolos de Seguridad y Sistema Operativo](docs/SECURITY_AND_OS_PROTOCOLS.md)
- [Guia Termica y BIOS Lenovo 82FE](docs/BIOS_AND_THERMAL_GUIDE_LENOVO_82FE.md)
- [Registro de Cambios (CHANGELOG)](CHANGELOG.md)
- [Contexto para Agentes](AGENTS.md) · [Claude Code](CLAUDE.md)

## Licencia

Distribuido bajo licencia **MIT**. Ver [LICENSE](LICENSE).
