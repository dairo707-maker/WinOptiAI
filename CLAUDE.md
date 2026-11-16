# CLAUDE.md — Contexto de Ingenieria para Agentes (Claude Code / Antigravity / Codex)

Este archivo contiene el contexto operativo, arquitectonico y de diseno de **WinOptiAI** (`v0.1.0`) para garantizar continuidad exacta entre sesiones de agentes y desarrolladores.

## Perfil del Proyecto y Propietario

- **Propietario:** Dairo (economista; comunicarse en espanol claro en UI y documentacion, codigo y docstrings tecnicos en ingles/espanol consistentes).
- **Hardware de referencia verificado (no suponer especificaciones):**
  - Equipo: **Lenovo `82FE` (IdeaPad 5)**
  - BIOS: **`FKCN51WW(V3.14)`** (UEFI + Secure Boot activo)
  - CPU: **Intel Core i5-1135G7** (Tiger Lake, 4C / 8T)
  - GPU: **Intel Iris Xe Graphics** (driver detectado inicialmente `30.0.101.1960`, objetivo recomendado `32.0.101.x`)
  - Memoria: **16 GB RAM** compartida con Iris Xe (escenario tipico saturado por VS Code, Antigravity, Claude, Chrome y language servers)
  - Disco: **KINGSTON SNV3S1000G** NVMe 1 TB (`C:\`) + sincronizacion activa con **OneDrive corporativo**
  - SO: **Windows 11 Home Single Language 25H2 (Build 26200)**

## Reglas Inviolables de Diseno UI/UX

1. **Estetica "Obsidian Acrylic" (Liquid Glass arquitectonico):**
   - Bordes estrictamente rectos (`border-radius: 0px` en QSS y `DWMWCP_DONOTROUND` en `dwmapi.dll`).
   - Lineas divisorias `1px` hairline, fondo translucido DWM Acrylic (`DWMWA_SYSTEMBACKDROP_TYPE = 3`).
   - Jerarquia monocromo / acero-hielo (`#E2E7ED`, `#9BA3AE`, `#0B0D10`). **Prohibidos los brillos neon, gradientes llamativos o colores saturados de "estetica IA".**
2. **Cero Emojis — 100% SVG Minimalistas:**
   - Prohibido usar emojis Unicode en codigo UI, etiquetas, notificaciones Tray o botones.
   - Usar exclusivamente iconos SVG geometricos de `assets/icons/*.svg` via `winoptiai.ui.svg_icons.load_svg_icon()`.
3. **Tipografia Embebida OFL:**
   - `Instrument Sans` (UI) + `IBM Plex Mono` (metricas, rutas, hashes, tags), cargadas desde `assets/fonts/`.
4. **Limpieza y Arranque Fluido:**
   - Maximo 1 accion primaria por vista; sin acumulacion de botones ni metricas redundantes.
   - Arranque en 2 fases: pintar ventana principal antes de lanzar escaneos WMI/disco en `QThreadPool`.

## Invariantes de Seguridad del Sistema Operativo

- **NUNCA** leer contenido ni hidratar archivos con atributos `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS`, `FILE_ATTRIBUTE_OFFLINE` o `FILE_ATTRIBUTE_UNPINNED` (proteccion OneDrive Cloud-Only en `win32_bridge.is_cloud_only_file`).
- **SIEMPRE** consultar `win32_bridge.get_locking_processes()` (`Rstrtmgr.dll`) y `safety_guard.is_safe_to_touch_file()` antes de mover o limpiar archivos.
- **NUNCA** tocar `PROTECTED_PATH_PREFIXES` (`Windows`, `System32`, `WinSxS`, `Program Files`, etc.) ni `PROTECTED_PROCESS_NAMES` (incluyendo `bdservicehost.exe` de Bitdefender y procesos de OneDrive).
- **NUNCA** modificar NVRAM/SPI de la BIOS directamente. Toda optimizacion termica se realiza con GUIDs oficiales de `powercfg` (`thermal_controller.py`) y auditoria read-only (`bios_auditor.py`).
- **Politica Hibrida SRE (`sre_policy.py`):** la automatizacion en segundo plano solo aplica EcoQoS/Working Set Trim si RAM libre `< 1.8 GB` por 3 muestras seguidas con histeresis de `300 s`. **En disco nunca se borra automaticamente.**

## Comandos Clave (siempre con `uv`)

```powershell
# Instalar / sincronizar entorno
uv sync --extra dev

# Ejecutar pruebas automatizadas (NUNCA declarar validado sin correr esto)
uv run pytest -v

# Ejecutar la aplicacion en modo desarrollo
uv run python -m winoptiai.app

# Compilar WinOptiAI-Portable.exe y WinOptiAI-Setup.exe
uv run python scripts/build_exe.py
```

## Convenciones de Git, Versionado y Notas

- Rama principal: `main`.
- Version unica en `VERSION` (`0.1.0`), sincronizada con `pyproject.toml` y `CHANGELOG.md`.
- Usar commits semanticos descriptivos en espanol (`feat(core): ...`, `fix(ui): ...`, `docs: ...`).
- Adjuntar `git notes` tecnicas con contexto de verificacion a los commits principales (`git log --show-notes`).
