# Protocolos de Seguridad y Sistema Operativo

## 1. Proteccion Estricta de OneDrive (Cloud-Only)

Los archivos marcados como solo en linea en OneDrive presentan los atributos Win32:
- `FILE_ATTRIBUTE_OFFLINE` (`0x00001000`)
- `FILE_ATTRIBUTE_RECALL_ON_OPEN` (`0x00040000`)
- `FILE_ATTRIBUTE_UNPINNED` (`0x00100000`)
- `FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS` (`0x00400000`)

WinOptiAI inspecciona `GetFileAttributesW` antes de abrir cualquier archivo. Si alguno de estos bits esta activo, el archivo queda excluido de forma inmediata, evitando hidrataciones involuntarias o consumo de red/disco.

## 2. Verificacion de Bloqueos con Windows Restart Manager

Antes de mover o limpiar archivos temporales, duplicados o huerfanos, `win32_bridge.get_locking_processes()` consulta `Rstrtmgr.dll`. Si cualquier proceso o servicio del sistema mantiene un descriptor abierto, la operacion se bloquea y se reporta el nombre del proceso responsable.

## 3. Listas Blancas Inviolables

- **Rutas excluidas permanentemente:** `C:\Windows` (salvo `Temp`, `Prefetch`, `Minidump` en modo temporal controlado), `C:\Program Files`, `C:\Program Files (x86)`, `C:\ProgramData\Microsoft`, `C:\ProgramData\Bitdefender`, `C:\Recovery`, `$Recycle.Bin`, `System Volume Information`.
- **Procesos protegidos:** kernel (`System`, `Registry`, `Memory Compression`), sesion (`csrss.exe`, `lsass.exe`, `smss.exe`, `wininit.exe`, `services.exe`, `svchost.exe`, `dwm.exe`), seguridad (`MsMpEng.exe`, `bdservicehost.exe`, `bdagent.exe`) y sincronizacion (`OneDrive.exe`, `FileCoAuth.exe`).

## 4. Principio de Cero Borrado Silencioso en Disco

Ninguna rutina automatica en segundo plano elimina o mueve archivos de usuario. Toda depuracion de duplicados o huerfanos ocurre bajo accion explicita hacia la **Boveda de Cuarentena** (`%LOCALAPPDATA%\WinOptiAI\Quarantine`) con hash SHA-256 para rollback integro.
