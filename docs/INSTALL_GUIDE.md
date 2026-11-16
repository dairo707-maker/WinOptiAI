# Guia de Instalacion — WinOptiAI

Esta guia explica como ubicar los ejecutables generados, completar la instalacion paso a paso en Windows 11 con seleccion de directorio, verificar la integridad criptografica (`SHA-256`) y desinstalar la aplicacion de forma limpia.

---

## 1. Donde encontrar el instalador y las variantes disponibles

Dentro de la carpeta `dist\` del proyecto (o en la seccion **Releases** de GitHub) se encuentran dos ejecutables oficiales:

1. **`WinOptiAI-Setup.exe` (Recomendado):** instalador nativo de Windows (Inno Setup 6) con asistente paso a paso, seleccion de directorio, creacion de accesos directos y desinstalador oficial integrado en Windows.
   - Ruta local en este proyecto: `dist\WinOptiAI-Setup.exe`
2. **`WinOptiAI-Portable.exe`:** ejecutable autonomo de un solo archivo (`--onefile`) ideal para ejecutar desde una memoria USB o carpeta sin instalacion previa.

---

## 2. Verificacion de Integridad (Opcional pero Recomendada)

Antes de ejecutar cualquier binario descargado de internet, compruebe que su firma SHA-256 coincida con `dist\SHA256SUMS.txt`:

```powershell
Get-FileHash .\dist\WinOptiAI-Setup.exe -Algorithm SHA256
Get-Content .\dist\SHA256SUMS.txt
```

> **Nota sobre Windows SmartScreen y Bitdefender:**
> Al ser un proyecto de codigo abierto compilado localmente o desde GitHub Actions sin un certificado comercial EV de pago, Windows Defender SmartScreen puede mostrar el aviso *"Windows protegio su PC"*. Para continuar tras comprobar el hash SHA-256: haga clic en **Mas informacion** y luego en **Ejecutar de todas formas**.

---

## 3. Instalacion Paso a Paso (`WinOptiAI-Setup.exe`)

Haga doble clic sobre **`WinOptiAI-Setup.exe`** y siga los 6 pasos del asistente estandar de Windows:

### Paso 1: Modo de Instalacion (Alcance)
El asistente le preguntara como desea instalar:
- **Instalar solo para mi (recomendado):** instala en `%LOCALAPPDATA%\Programs\WinOptiAI` sin requerir permisos de administrador (UAC).
- **Instalar para todos los usuarios:** instala en `C:\Program Files\WinOptiAI` (solicitara confirmacion UAC de Windows).

### Paso 2: Acuerdo de Licencia
Revise la licencia de codigo abierto **MIT** y seleccione **Acepto el acuerdo** -> **Siguiente >**.

### Paso 3: Seleccionar Carpeta de Destino (Directorio)
Por defecto el asistente propone la ruta segun el alcance elegido en el Paso 1.
- Para instalar en otra unidad o carpeta personalizada (por ejemplo `D:\Herramientas\WinOptiAI`), haga clic en el boton **Examinar...**, elija el directorio deseado y pulse **Siguiente >**.
- En la parte inferior podra verificar el espacio libre disponible y el espacio requerido (~115 MB descomprimidos).

### Paso 4: Carpeta del Menu Inicio
Confirme el nombre de carpeta del Menu Inicio (`WinOptiAI`) o seleccione *No crear una carpeta en el Menu Inicio* -> **Siguiente >**.

### Paso 5: Seleccionar Tareas Adicionales
Marque segun su preferencia:
- **Crear un acceso directo en el Escritorio**
- **Crear acceso directo en el Menu Inicio**
- **Iniciar WinOptiAI minimizado en la bandeja al arrancar Windows** *(opcional, desmarcado por defecto; util si desea monitoreo pasivo SRE continuo)*

### Paso 6: Instalacion y Finalizacion
Haga clic en **Instalar**. Verá la barra de progreso copiando `WinOptiAI.exe`, la licencia y las guias tecnicas. Al finalizar, deje marcada la casilla **Ejecutar WinOptiAI ahora** y pulse **Finalizar**.

---

## 4. Desinstalacion Limpia

WinOptiAI registra su desinstalador oficial en Windows y nunca deja procesos ocultos ni archivos huerfanos en el sistema:

1. Abra **Configuracion de Windows** -> **Aplicaciones** -> **Aplicaciones instaladas** (o ejecute *Desinstalar WinOptiAI* desde el Menu Inicio).
2. Busque **WinOptiAI** y haga clic en **Desinstalar**.
3. Si desea eliminar tambien la Boveda de Cuarentena y configuracion local, revise manualmente la carpeta `%LOCALAPPDATA%\WinOptiAI` despues de restaurar cualquier archivo necesario.
