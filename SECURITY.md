# Politica de seguridad de WinOptiAI

WinOptiAI mueve, restaura y elimina archivos, cambia planes de energia y puede ejecutar comandos
con permisos de administrador. Por eso tratamos los fallos de seguridad y de proteccion de datos
con prioridad.

## Versiones con soporte

| Version | Soporte de seguridad |
| ------- | -------------------- |
| Ultima publicada en [Releases](https://github.com/dairo707-maker/WinOptiAI/releases/latest) | Si |
| Versiones anteriores | No: actualice desde *Acerca de > Buscar actualizaciones* |

## Como reportar una vulnerabilidad

**No abra un issue publico** para problemas de seguridad.

1. En el repositorio, entre a la pestana **Security** y pulse **Report a vulnerability**
   (reporte privado de GitHub). Solo el responsable del proyecto lo vera.
2. Incluya: version de WinOptiAI, version de Windows, pasos para reproducir, impacto esperado y,
   si puede, `crash.log` anonimizado (Diagnostico > Copiar Diagnostico).
3. No incluya contrasenas, tokens ni datos personales.

Tiempos objetivo: acuse de recibo en 3 dias habiles, evaluacion inicial en 7 dias y correccion o
mitigacion publicada en la siguiente version segun la gravedad. Se dara credito a quien reporte, si
lo desea.

## Que consideramos de seguridad

- Perdida o dano de datos: archivos movidos, eliminados o sobrescritos sin confirmacion, archivos
  de programas o del sistema tratados como sobrantes, restauraciones incompletas.
- Hidratacion o lectura de archivos de OneDrive marcados como "solo en la nube".
- Escalada de privilegios o ejecucion de comandos no previstos (UAC, consolas elevadas).
- Exposicion de tokens de Microsoft Graph (se guardan cifrados con DPAPI) o de datos personales en
  informes de error (que se anonimizan antes de enviarse).
- Integridad del actualizador (descarga desde GitHub Releases y verificacion SHA-256).
- Procesos que sigan activos despues de cerrar la app.

Fuera de alcance: problemas que requieren que un atacante ya controle la cuenta de Windows del
usuario, y fallos de terceros (Windows, OneDrive, antivirus) que WinOptiAI no puede corregir.

## Principios de diseno

El detalle tecnico esta en [`docs/SECURITY_AND_OS_PROTOCOLS.md`](docs/SECURITY_AND_OS_PROTOCOLS.md).
En resumen:

- Nada se elimina directamente: todo pasa por la Boveda de Cuarentena, reversible, con manifiesto
  confirmado por lotes. Solo "Depurar / Vaciar Boveda" elimina, con confirmacion.
- Rutas del sistema, carpetas de programas, entornos de desarrollo y la propia Boveda nunca se
  escanean ni se mueven.
- Comprobacion de bloqueos (Restart Manager) antes de mover archivos.
- Sin telemetria automatica: los informes de error solo se envian si el usuario lo decide.
- Al salir, la app cancela sus tareas en un punto seguro y cierra todos los procesos que inicio.
