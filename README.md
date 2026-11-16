# WinOptiAI

Gestor nativo de almacenamiento, optimizacion de procesos para IA agentica, control termico y auditoria UEFI/BIOS para **Windows 11**.

## Capacidades Principales

- **Almacenamiento con Seguridad Kernel:**
  - Proteccion estricta de marcadores **OneDrive Cloud-Only** (`GetFileAttributesW`) para evitar descargas accidentales.
  - Verificacion de bloqueos en tiempo real con **Windows Restart Manager (`Rstrtmgr.dll`)**.
  - Motor de deduplicacion **BLAKE3 en 4 etapas** con opcion de **Hardlinks NTFS** o traslado a **Boveda de Cuarentena** con restauracion SHA-256.
  - Escaneo seguro de temporales, caches de desarrollo (`uv`, `pip`, `npm`, `NuGet`, `D3DSCache`) y artefactos huerfanos.
- **Optimizacion para IA Agentica (Local y Online):**
  - Politica hibrida **SRE** con histeresis de 5 minutos: monitoreo pasivo ligero y alivio automatico de memoria si la RAM libre cae bajo `1.8 GB`.
  - Aplicacion nativa de **Windows 11 EcoQoS (Efficiency Mode)** y compactacion segura de Working Set (`EmptyWorkingSet`).
  - Detector de procesos zombis huerfanos (`node.exe`, `python.exe`, `uv.exe`, servidores MCP).
- **Control Termico y Auditoria BIOS/UEFI:**
  - Perfiles termicos oficiales mediante `powercfg` (`PERFBOOSTMODE` y `EPP`) para evitar recalentamiento en laptops Intel Core / Iris Xe.
  - Auditoria de firmware SMBIOS/WMI, salud SMART/TRIM NVMe, controlador grafico Intel Iris Xe y reinicio asistido a UEFI (`shutdown /r /fw`).

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
