# AGENTS.md — Guia Multi-Agente (Antigravity, Claude Code, Codex, Cursor)

Este repositorio sigue el estandar de contexto compartido. Lea `CLAUDE.md` como referencia maestra de hardware, estetica UI (`0px` Obsidian Acrylic, cero emojis, `Instrument Sans` + `IBM Plex Mono`) e invariantes de seguridad del sistema operativo.

## Mapa de Modulos

- `src/winoptiai/core/win32_bridge.py`: Puente `ctypes` a `dwmapi.dll`, `kernel32.dll`, `psapi.dll`, `Rstrtmgr.dll` y `shell32.dll`.
- `src/winoptiai/core/safety_guard.py`: Listas blancas OS/antivirus y `QuarantineVault` transaccional con SHA-256 y rollback.
- `src/winoptiai/core/sre_policy.py`: Motor de politica hibrida SRE (histeresis RAM + registro de auditoria `audit.jsonl`).
- `src/winoptiai/storage/`: `junk_scanner.py` (temporales y caches), `duplicate_finder.py` (BLAKE3 en 4 etapas + hardlinks NTFS), `orphan_hunter.py` (artefactos huerfanos verificados con Restart Manager).
- `src/winoptiai/ai_optimizer/process_manager.py`: Telemetria RAM, `run_ai_boost()` (EcoQoS + Working Set Trim) y cazador de workers MCP zombis.
- `src/winoptiai/thermal_bios/`: `thermal_controller.py` (perfiles `powercfg` EPP/Boost) y `bios_auditor.py` (WMI SMBIOS/GPU/NVMe + reinicio guiado UEFI).
- `src/winoptiai/ui/`: Interfaz `PySide6` Obsidian Acrylic, iconos SVG (`assets/icons/`), fuentes OFL (`assets/fonts/`) y `WinOptiTray`.
- `scripts/build_exe.py` & `packaging/`: Generacion de `.ico`, `WinOptiAI-Portable.exe`, `WinOptiAI-Setup.exe` y plantilla Inno Setup `installer.iss`.

## Checklist Obligatorio antes de Confirmar Cambios

1. Verificar cero emojis en `src/winoptiai/` ejecutando `uv run pytest -v`.
2. Mantener `border-radius: 0px` y paleta monocromo Obsidian Acrylic en toda modificacion visual.
3. No introducir dependencias fuera de `pyproject.toml` sin actualizar `uv` (`uv add` / `uv sync`).
4. Actualizar `CHANGELOG.md` y adjuntar `git note` si el cambio afecta arquitectura o seguridad.
