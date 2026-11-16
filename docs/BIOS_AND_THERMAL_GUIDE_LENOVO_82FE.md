# Guia Termica, Drivers y BIOS — Lenovo 82FE (i5-1135G7 + Iris Xe)

Esta guia recoge los parametros verificados para el equipo **Lenovo IdeaPad 5 (`82FE`)** con **BIOS `FKCN51WW(V3.14)`**, procesador **Intel Core i5-1135G7** (Tiger Lake 4C/8T) e **Intel Iris Xe Graphics**.

## 1. Seguridad de Firmware (Por que no se escribe NVRAM)

Windows 11 con **Secure Boot** y proteccion de integridad del kernel bloquea la escritura directa en memoria SPI/UEFI desde aplicaciones de usuario. Modificar variables NVRAM sin firma del fabricante conlleva riesgo real de corrupcion de arranque. Por ello, WinOptiAI implementa:
1. **Auditoria de solo lectura** via WMI/SMBIOS.
2. **Control termico en caliente** mediante GUIDs oficiales de `powercfg` (reversible con 1 clic).
3. **Reinicio asistido a UEFI** (`shutdown /r /fw`) para ajustes oficiales dentro del menu del fabricante.

## 2. Checklist Recomendado en UEFI (`FKCN51WW`)

Al reiniciar hacia el menu UEFI:
- `Configuration -> System Performance Mode`: seleccionar **`Intelligent Cooling`** para sesiones de IA agentica online (evita ráfagas agresivas del ventilador y reduce picos termicos) o **`Extreme Performance`** solo si va a correr inferencia local corta conectado a corriente.
- `Configuration -> Intel Virtualization Technology (VT-x / VT-d)`: **`Enabled`** (necesario para contenedores, WSL2 y entornos aislados).
- `Configuration -> Flip to Boot` / `Always On USB`: segun preferencia; desactivar `Always On USB` en mochila reduce descarga parasita.
- En Windows (Lenovo Vantage o UEFI): activar **Modo Conservacion de Bateria** si trabaja conectado permanentemente (limita carga entre 60% y 80% y disminuye temperatura del chasis).

## 3. Actualizacion de Controlador Intel Iris Xe (Clave para IA Local)

En el diagnostico inicial se detecto la version **`30.0.101.1960`**. Para ejecutar modelos locales cuantizados con aceleracion por GPU integrada (**DirectML**, **Vulkan** en `llama.cpp`/`Ollama` o **OpenVINO**) y aprovechar WDDM 3.2 en Windows 11 25H2, se recomienda actualizar a la rama **`32.0.101.x`** desde el sitio oficial de Intel o **Intel Driver & Support Assistant**.

## 4. Perfiles Termicos en WinOptiAI (`powercfg`)

- **Frio / Silencioso:** `PERFBOOSTMODE = Efficient Enabled (3)` en CA / `Disabled (0)` en bateria, `EPP = 65%`, estado maximo `99%`. Ideal para trabajar con VS Code, Claude, Antigravity y navegadores sin calentar la base ni disparar el ventilador.
- **Equilibrado Inteligente:** `Efficient Aggressive (4)`, `EPP = 40%`.
- **IA Local Maxima:** `Aggressive (2)`, `EPP = 15%`. Recomendado solo sobre superficie ventilada y conectado al cargador.
