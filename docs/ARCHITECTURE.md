# Arquitectura Tecnica — WinOptiAI

## Vision General

WinOptiAI esta estructurado en cuatro capas desacopladas para garantizar bajo consumo en reposo (~40 MB RAM), arranque fluido en dos fases (`< 300 ms`) y cero bloqueos en el hilo grafico:

1. **Capa de Puente Win32 (`src/winoptiai/core/win32_bridge.py`):**
   - `dwmapi.dll`: aplica `DWMWA_SYSTEMBACKDROP_TYPE = 3` (Acrylic oscuro) y `DWMWA_WINDOW_CORNER_PREFERENCE = 1` (`DWMWCP_DONOTROUND`, bordes rectos `0px`).
   - `kernel32.dll` / `psapi.dll`: lectura de atributos OneDrive (`GetFileAttributesW`), enlaces duros NTFS (`CreateHardLinkW`), `SetProcessInformation(ProcessPowerThrottling)` (EcoQoS) y `EmptyWorkingSet` (`PROCESS_SET_QUOTA`).
   - `Rstrtmgr.dll`: sesiones del Windows Restart Manager (`RmStartSession`, `RmRegisterResources`, `RmGetList`) para verificar bloqueos reales antes de tocar archivos.
   - `shell32.dll`: envio a Papelera (`SHFileOperationW`) y elevacion UAC bajo demanda (`ShellExecuteW(..., "runas")`).

2. **Capa de Guardrails y Politica SRE (`safety_guard.py`, `sre_policy.py`):**
   - Listas blancas inmutables de rutas del sistema operativo y procesos criticos/antivirus.
   - **Boveda de Cuarentena** transaccional (`manifest.json` con SHA-256) y restauracion 1-clic.
   - **Guardia Hibrido SRE:** evalua la presion de RAM libre cada `2 s` (o `10 s` minimizado). Solo interviene automaticamente cuando la memoria libre baja de `1.8 GB` durante 3 muestras consecutivas, respetando una ventana de enfriamiento (*hysteresis*) de `300 s`.

3. **Motores de Dominio (`storage/`, `ai_optimizer/`, `thermal_bios/`):**
   - **Duplicados BLAKE3 en 4 etapas:** Filtro de seguridad/OneDrive -> Tamano exacto -> Pre-hash 4 KB inicio+fin -> BLAKE3 completo + comprobacion de inodo NTFS (`st_ino`).
   - **Optimizacion IA Agentica:** compactacion segura de Working Set en apps pesadas, EcoQoS en segundo plano y deteccion de workers `node`/`python`/`uv` con proceso padre muerto.
   - **Termica y Auditoria:** regulacion oficial `powercfg` (`PERFBOOSTMODE`, `PERFEPP`) y lectura CIM/WMI read-only de SMBIOS, Iris Xe y NVMe.

4. **Interfaz "Obsidian Acrylic" (`src/winoptiai/ui/`):**
   - Construida sobre `PySide6` con fuentes OFL embebidas (`Instrument Sans` + `IBM Plex Mono`) e iconos SVG geometricos propios.
   - Fase 1 renderiza el shell visual; Fase 2 (`QTimer.singleShot(80, ...)`) ejecuta la recoleccion WMI y de disco en `QThreadPool`.
