# AGENTS.md — Guia Multi-Agente (Antigravity, Claude Code, Codex, Cursor)

Este repositorio sigue el estandar de contexto compartido. Lea `CLAUDE.md` como referencia maestra de hardware, estetica UI (`0px` Obsidian Acrylic, cero emojis, `Instrument Sans` + `IBM Plex Mono`) e invariantes de seguridad del sistema operativo.

## Mapa de Modulos

- `src/winoptiai/core/win32_bridge.py`: Puente `ctypes` a `dwmapi.dll`, `kernel32.dll`, `psapi.dll`, `Rstrtmgr.dll` y `shell32.dll` (incluye `apply_window_theme`, `reveal_in_explorer`).
- `src/winoptiai/core/safety_guard.py`: Listas blancas OS/antivirus y `QuarantineVault` transaccional con SHA-256 y rollback.
- `src/winoptiai/core/sre_policy.py`: Motor de politica hibrida SRE (calibracion dinamica RAM + histeresis + `audit.jsonl`).
- `src/winoptiai/core/telemetry.py`: Lector `pdh.dll` independiente de idioma (frecuencia CPU MHz, Turbo %, carga por nucleo y sonda termica ACPI/NVMe).
- `src/winoptiai/core/i18n.py` & `updater.py`: Soporte ES/EN/PT sincronizado con Inno Setup 6 y auto-actualizador SHA-256 contra GitHub Releases (`dairo707-maker/WinOptiAI`).
- `src/winoptiai/storage/`: `junk_scanner.py`, `duplicate_finder.py` (BLAKE3 + reglas autolimpiador + hardlinks NTFS), `tree_analyzer.py` (arbol jerarquico y formatos), `orphan_hunter.py`.
- `src/winoptiai/ai_optimizer/process_manager.py`: Telemetria RAM, `run_ai_boost()` (EcoQoS + Working Set Trim) y cazador de workers MCP zombis.
- `src/winoptiai/thermal_bios/`: `thermal_controller.py` (perfiles `powercfg` EPP/Boost) y `bios_auditor.py` (perfilador universal multi-hardware + acciones 1-clic).
- `src/winoptiai/ui/`: Interfaz `PySide6` Dual Tema (`Obsidian Acrylic` oscuro / `Alabaster Frost` claro, `0px`), tablas ordenables, vista previa de duplicados, `AboutUpdaterDialog`, iconos SVG y `WinOptiTray`.
- `scripts/build_exe.py` & `packaging/`: Generacion de `.ico`, `WinOptiAI-Portable.exe` y `WinOptiAI-Setup.exe` multilingue (ES/EN/PT) con Inno Setup 6.

## Checklist Obligatorio antes de Confirmar Cambios

1. Verificar cero emojis en `src/winoptiai/` ejecutando `uv run pytest -v`.
2. Mantener `border-radius: 0px` y paleta monocromo Obsidian Acrylic en toda modificacion visual.
3. No introducir dependencias fuera de `pyproject.toml` sin actualizar `uv` (`uv add` / `uv sync`).
4. Actualizar `CHANGELOG.md` y adjuntar `git note` si el cambio afecta arquitectura o seguridad.
