# Protocolos de Seguridad y Sistema Operativo

## 1. Proteccion Estricta de OneDrive (Cloud-Only) y Nube

Los archivos marcados como solo en linea en OneDrive presentan los atributos Win32:
- `FILE_ATTRIBUTE_OFFLINE` (`0x00001000`)
- `FILE_ATTRIBUTE_RECALL_ON_OPEN` (`0x00040000`)
- `FILE_ATTRIBUTE_UNPINNED` (`0x00100000`)
- `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` (`0x00400000`)

WinOptiAI inspecciona `GetFileAttributesW` antes de abrir, hashear o previsualizar cualquier archivo. **Carpetas (v0.5.4):** OneDrive marca sus carpetas con `UNPINNED` aunque esten en disco; listar una carpeta no descarga contenido, asi que los recorridos (`win32_bridge.attrs_skip_entry`) solo omiten carpetas `OFFLINE`/`RECALL_ON_OPEN`/`RECALL_ON_DATA_ACCESS`, y cada archivo se sigue evaluando con la mascara completa. En modo `OneDrive Nube`, la deshidratacion local usa unicamente `SetFileAttributesW` (`+U -P`) protegiendo repositorios (`.git`, `.venv`, `node_modules`); las acciones en Microsoft Graph usan OAuth 2.0 PKCE con tokens cifrados localmente via DPAPI (`CryptProtectData`), excluyen carpetas compartidas de terceros por defecto y envian solo a la Papelera de OneDrive (recuperable).

## 2. Verificacion de Bloqueos (Restart Manager y Fallback NTFS)

Antes de mover o limpiar duplicados o huerfanos, `win32_bridge.get_locking_processes()` consulta `Rstrtmgr.dll`. En directorios temporales masivos (`> 400` archivos), `junk_scanner.py` evita lanzar miles de sesiones RPC y usa deteccion atomica nativa NTFS (`os.replace` capturando `WinError 32` / `PermissionError`), protegiendo archivos en uso y la carpeta temporal `_MEIPASS` activa sin bloquear la UI.

## 3. Listas Blancas Inviolables y AI Boost Seguro

- **Rutas excluidas permanentemente:** `C:\Windows` (salvo excepciones temporales explícitas en `EXPLICIT_TEMP_ALLOWLIST`: `Temp`, `Prefetch`, `Minidump`, `SoftwareDistribution\Download`, `DeliveryOptimization`), `C:\Program Files`, `C:\Program Files (x86)`, `C:\ProgramData\Microsoft` (salvo `WER`), `C:\ProgramData\Bitdefender`, `C:\Recovery`, `$Recycle.Bin`, `System Volume Information`.
- **Procesos protegidos:** kernel (`System`, `Registry`, `Memory Compression`), sesion (`csrss.exe`, `lsass.exe`, `smss.exe`, `wininit.exe`, `services.exe`, `svchost.exe`, `dwm.exe`), seguridad (`MsMpEng.exe`, `bdservicehost.exe`, `bdagent.exe`), sincronizacion (`OneDrive.exe`, `FileCoAuth.exe`), el propio proceso, la ventana en primer plano (`get_foreground_pid()`) y agentes IA/IDEs (`AI_FOREGROUND_AGENTS`).

## 4. Cero Borrado Silencioso, Hardlinks Seguros y Retencion 30d

- Ninguna rutina automatica en segundo plano elimina archivos de usuario en disco. Todo cambio manual envia a la **Boveda de Cuarentena** (`%LOCALAPPDATA%\WinOptiAI\Quarantine`) con respaldo de hash SHA-256 para restauracion integra (al arranque solo expiran automaticamente lotes `Basura:*` con mas de 30 dias).
- Todo enlace duro NTFS (`duplicate_finder.py`) re-verifica tamano y hash BLAKE3 justo antes de ejecutarse y exige confirmacion explicita del usuario.

## 5. Telemetria de Fallos Local y Anonimizacion

`CrashGuard` y `CrashReporter` operan 100% en local (`%LOCALAPPDATA%\WinOptiAI\crash.log` y `session_lock.json`) sin credenciales embebidas ni telemetria oculta. Si el usuario opta por abrir un reporte en GitHub Issues, la app anonimiza previamente usuario de Windows, nombre de equipo, organizacion de OneDrive y correos electronico antes de mostrarlo para revision manual.
