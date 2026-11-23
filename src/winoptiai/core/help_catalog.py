"""Centralized catalog of hover tooltips, per-section benefit guides, and internal user manual."""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Hover tooltips (2-3 lines: what it does + what it improves + safety level)
# ---------------------------------------------------------------------------
TOOLTIPS: dict[str, str] = {
    # Navigation & Sidebar
    "nav_overview": (
        "Panel principal con RAM, disco, CPU/temperatura, graficos de 24 h / 7 d y Guardia SRE.\n"
        "Mejora: te permite detectar cuellos de botella de memoria o disco en segundos.\n"
        "Seguridad: solo lectura; ninguna metrica modifica el sistema."
    ),
    "nav_storage": (
        "Gestor de almacenamiento: Temporales, Duplicados BLAKE3, Arbol, Huerfanos, Cuarentena y OneDrive.\n"
        "Mejora: recupera gigabytes reales sin romper programas ni descargar archivos de la nube.\n"
        "Seguridad: todo borrado pasa primero por la Boveda de Cuarentena recuperable."
    ),
    "nav_processes": (
        "Monitor de procesos en vivo, compactacion RAM/EcoQoS y cazador de workers MCP/Node/Python.\n"
        "Mejora: reduce consumo de RAM en apps pesadas y cierra procesos zombis sin padre.\n"
        "Seguridad: nunca toca tu ventana activa, IDEs, antivirus ni procesos del sistema."
    ),
    "nav_thermal": (
        "Perfiles energeticos en caliente (powercfg), telemetria PDH/ACPI, S.M.A.R.T. y auditoria BIOS/OEM.\n"
        "Mejora: baja temperatura y ruido del ventilador o libera Turbo maximo para IA local.\n"
        "Seguridad: crea respaldo del plan de energia antes de cada ajuste; nunca flashea BIOS."
    ),
    "nav_apps": (
        "Administrador de aplicaciones del usuario: inventario, ultimo uso real, actualizador winget y desinstalador.\n"
        "Mejora: actualiza software desactualizado en 1 clic o desinstala programas olvidados limpiando residuos.\n"
        "Seguridad: protege Windows, antivirus, drivers y WinOptiAI; los restos opcionales van a Cuarentena."
    ),
    "nav_startup": (
        "Gestor de aplicaciones que arrancan con Windows con sugerencia inteligente tipo semaforo.\n"
        "Mejora: acelera el encendido y reduce RAM consumida al iniciar pausando apps que casi no usas.\n"
        "Seguridad: desactivacion 100% reversible (StartupApproved) y respaldo previo; nunca quita antivirus/drivers."
    ),
    "apps_scan": (
        "Escanea el Registro de Windows y cruza la fecha de ultimo uso real (BAM/Prefetch) de cada app.\n"
        "Mejora: identifica programas olvidados que ocupan disco sin usarse.\n"
        "Seguridad: operacion 100% de solo lectura."
    ),
    "apps_check_updates": (
        "Consulta el repositorio oficial winget para detectar versiones nuevas de tus programas.\n"
        "Mejora: mantiene tus apps seguras y actualizadas sin buscar instaladores manuales.\n"
        "Seguridad: consulta sin instalar cambios automaticos."
    ),
    "apps_upgrade": (
        "Actualiza silenciosamente la aplicacion seleccionada usando Microsoft winget.\n"
        "Mejora: corrige fallos de seguridad y obtiene la ultima version oficial en 1 clic.\n"
        "Seguridad: solo actua sobre apps no protegidas elegidas por ti."
    ),
    "apps_uninstall": (
        "Lanza el desinstalador oficial (o winget) del programa seleccionado y ofrece limpiar restos en AppData.\n"
        "Mejora: recupera espacio de aplicaciones que ya no necesitas.\n"
        "Seguridad: pide confirmacion y los restos opcionales se mueven a Cuarentena reversible."
    ),
    "startup_scan": (
        "Inspecciona el Registro Run, carpetas Inicio, memoria RAM actual y frecuencia real de uso.\n"
        "Mejora: clasifica en semaforo (Mantener / Pausar / Desactivar) que frena tu encendido.\n"
        "Seguridad: analisis de solo lectura."
    ),
    "startup_apply_smart": (
        "Desactiva de forma reversible solo las entradas marcadas en rojo (DESACTIVAR: sin uso reciente o bloatware).\n"
        "Mejora: aligera el arranque de Windows en 1 clic manteniendo intactos drivers y seguridad.\n"
        "Seguridad: guarda respaldo previo y puedes reactivarlas cuando quieras."
    ),
    "startup_disable": (
        "Pausa o desactiva en StartupApproved las entradas seleccionadas para que no arranquen solas.\n"
        "Mejora: ahorra RAM desde que enciendes el equipo.\n"
        "Seguridad: 100% reversible."
    ),
    "startup_enable": (
        "Reactiva las entradas de inicio seleccionadas para que vuelvan a abrirse al iniciar sesion."
    ),
    "btn_tour": (
        "Abre el tour guiado de 5 pasos y ejecuta una prueba rapida segura de este equipo.\n"
        "Mejora: calibra el umbral SRE y comprueba salud S.M.A.R.T., sensores y reinicios pendientes.\n"
        "Seguridad: verificacion 100% de solo lectura (~3-5 s)."
    ),
    "btn_about": (
        "Abre Acerca de, el Manual de Uso interno, Diagnostico de errores y el auto-actualizador.\n"
        "Mejora: te permite aprender cada funcion y mantener WinOptiAI al dia con verificacion SHA-256.\n"
        "Seguridad: consulta solo GitHub Releases oficiales; nunca instala sin tu confirmacion."
    ),
    "lang_combo": (
        "Cambia el idioma principal de la interfaz entre Espanol (ES), Ingles (EN) y Portugues (PT).\n"
        "Mejora: adapta menus, titulos y acciones al instante sin reiniciar la aplicacion."
    ),
    # Top Utility Bar
    "task_pill": (
        "Muestra el avance y tiempo estimado (ETA) de las tareas en segundo plano.\n"
        "Mejora: haz clic para abrir el Centro de Notificaciones, ver detalles o retomar sesiones guardadas."
    ),
    "pause_top": (
        "Pausa temporalmente en memoria la tarea en curso o la reanuda donde quedo.\n"
        "Mejora: libera disco y CPU al instante si necesitas usar otra aplicacion pesada.\n"
        "Seguridad: se detiene en un punto cooperativo seguro sin corromper archivos."
    ),
    "save_pause_top": (
        "Guarda el progreso actual en disco (%LOCALAPPDATA%\\WinOptiAI\\sessions) y detiene la tarea.\n"
        "Mejora: permite cerrar o reiniciar el PC y retomar limpiezas largas otro dia sin repetir trabajo.\n"
        "Seguridad: lo ya procesado queda asegurado en la Boveda de Cuarentena."
    ),
    "cancel_top": (
        "Detiene de forma segura la tarea activa en segundo plano.\n"
        "Mejora: cancela analisis o limpiezas largas sin dejar procesos huerfanos.\n"
        "Seguridad: conserva intacto el registro de lo que ya se movio a Cuarentena."
    ),
    "resume_session": (
        "Abre las sesiones pausadas y guardadas anteriormente para retomarlas donde quedaron.\n"
        "Mejora: evita volver a escanear o mover miles de archivos desde cero."
    ),
    "uac_btn": (
        "Relanza WinOptiAI con permisos de Administrador (UAC de Windows).\n"
        "Mejora: habilita limpieza profunda de Windows\\Temp, Windows Update, Minidump y lectura termica ACPI/NVMe.\n"
        "Seguridad: mantiene intactas todas las listas blancas del sistema operativo."
    ),
    "bell_btn": (
        "Abre el Centro de Notificaciones, tareas activas, sesiones guardadas y diagnostico.\n"
        "Mejora: centraliza avisos de AI Boost, actualizaciones y cierres inesperados sin ventanas invasivas."
    ),
    # Overview View
    "overview_boost": (
        "Compacta memoria RAM inactiva (Working Set) y aplica Windows 11 EcoQoS a apps en segundo plano.\n"
        "Mejora: libera cientos de MB o GB de RAM al instante para tus agentes IA y navegadores.\n"
        "Seguridad: no cierra ninguna aplicacion; protege tu ventana activa, IDEs y antivirus."
    ),
    "overview_focus": (
        "Activa o desactiva Modo Enfoque: pasa apps en segundo plano a EcoQoS + prioridad E/S baja y evita suspension.\n"
        "Mejora: prioriza disco, CPU y energia para tu sesion activa o modelo IA local.\n"
        "Seguridad: 100% reversible en un clic o al cerrar la app; nunca toca IDEs ni antivirus."
    ),
    "metric_ram": (
        "Memoria RAM fisica libre y en uso en tiempo real.\n"
        "Mejora: si baja del umbral SRE por 3 muestras seguidas (histeresis 5 min), AI Boost alivia presion."
    ),
    "metric_disk": (
        "Espacio disponible en la unidad principal C:.\n"
        "Mejora: mantener al menos 15-20% libre protege la velocidad y vida util del SSD/NVMe."
    ),
    "metric_cpu_temp": (
        "Uso total de CPU, frecuencia real (pdh.dll) y temperatura ACPI/NVMe cuando esta disponible.\n"
        "Mejora: ayuda a elegir entre perfil Frio/Silencioso o IA Local Maxima."
    ),
    "metric_sre": (
        "Estado del Guardia Hibrido SRE y perfil termico activo.\n"
        "Mejora: automatiza alivio de RAM sin borrar nunca archivos en disco."
    ),
    # Storage Mode Tabs
    "mode_junk": (
        "Escanea temporales de usuario, caches de navegadores (sin sesiones), uv/pip/npm/VS Code y Windows Update.\n"
        "Mejora: libera espacio acumulado rapidamente sin perder contraseñas ni proyectos.\n"
        "Seguridad: omite archivos en uso (NTFS/Restart Manager) y respalda todo en Cuarentena."
    ),
    "mode_dups": (
        "Busca archivos identicos byte a byte mediante hash criptografico BLAKE3 en 4 etapas.\n"
        "Mejora: elimina copias redundantes en Descargas o Documentos conservando siempre al menos 1 copia.\n"
        "Seguridad: protege programas, entornos (.venv, AppData, drivers) y carpetas copiadas completas."
    ),
    "mode_tree": (
        "Mapa jerarquico (treemap), arbol de carpetas con carga perezosa y top-100 de archivos mas pesados.\n"
        "Mejora: descubre en segundos que carpetas o formatos (videos, backups, bases) llenan tu disco.\n"
        "Seguridad: nunca hidrata archivos OneDrive solo-en-la-nube."
    ),
    "mode_orphans": (
        "Detecta carpetas residuales en AppData/ProgramData cuyo programa padre ya fue desinstalado.\n"
        "Mejora: limpia restos viejos de apps eliminadas.\n"
        "Seguridad: requiere seleccion explicita y mueve a Cuarentena con restauracion en 1 clic."
    ),
    "mode_quarantine": (
        "Boveda transaccional donde descansan los elementos movidos antes de borrarse definitivamente.\n"
        "Mejora: te da tranquilidad total con restauracion SHA-256 y purga controlada.\n"
        "Seguridad: solo lotes de Basura expirados (>30 dias) se depuran automaticamente."
    ),
    "mode_onedrive": (
        "Optimizador hibrido para OneDrive Local (Files On-Demand) y Nube (Microsoft Graph PKCE).\n"
        "Mejora: libera espacio local en SSD pasando archivos antiguos a 'Solo en la nube' sin borrarlos.\n"
        "Seguridad: protege repositorios .git/.venv, cifra tokens con DPAPI y usa la Papelera de OneDrive."
    ),
    # Storage Action Controls
    "storage_primary": (
        "Inicia el analisis de solo lectura para la pestana seleccionada (Temporales, Duplicados, Arbol, etc.).\n"
        "Mejora: calcula exactamente cuanto espacio puedes recuperar antes de tocar un solo archivo.\n"
        "Seguridad: solo inspecciona metadatos y hashes; no borra nada."
    ),
    "storage_secondary": (
        "Ejecuta la accion segura principal sobre las filas seleccionadas (mover a Cuarentena, restaurar o deshidratar).\n"
        "Mejora: aplica la limpieza elegida con registro en historial y opcion de deshacer.\n"
        "Seguridad: siempre reversible desde Cuarentena o Papelera de OneDrive."
    ),
    "storage_tertiary": (
        "Accion complementaria segun la pestana: Hardlink NTFS en Duplicados o Purgar seleccionados en Cuarentena.\n"
        "Mejora: Hardlink ahorra 100% del espacio manteniendo ambas rutas; Purgar libera el disco definitivamente.\n"
        "Seguridad: re-verifica BLAKE3 antes de enlazar y pide confirmacion explicita."
    ),
    "storage_select_all": (
        "Marca o desmarca todas las filas visibles de la tabla actual.\n"
        "Mejora: agiliza limpiezas o restauraciones masivas mostrando conteo y peso seleccionado."
    ),
    "storage_reveal": (
        "Abre el Explorador de Windows ubicando y resaltando el archivo o carpeta seleccionada.\n"
        "Mejora: te permite inspeccionar manualmente cualquier elemento antes de limpiarlo."
    ),
    "storage_autoclean": (
        "Aplica la regla elegida sobre todos los grupos duplicados elegibles (mostrando resumen y confirmacion).\n"
        "Mejora: limpia duplicados repetitivos en segundos protegiendo siempre una copia original.\n"
        "Seguridad: ignora programas, carpetas copiadas y envia copias a Cuarentena."
    ),
    "storage_rule": (
        "Define que copia se conserva en cada grupo duplicado (mas antigua, mas reciente o ruta mas corta).\n"
        "Mejora: adapta la deduplicacion a tu forma de organizar archivos."
    ),
    "storage_empty_vault": (
        "Elimina permanentemente todos los elementos de la Boveda de Cuarentena (pide confirmacion).\n"
        "Mejora: convierte en espacio libre real en C: todo lo que ya validaste que no necesitas.\n"
        "Seguridad: accion definitiva (irreversible); verifica antes que no requieras restaurar nada."
    ),
    "storage_od_connect": (
        "Conecta tu cuenta personal o corporativa de OneDrive via OAuth 2.0 PKCE.\n"
        "Mejora: habilita cuota de nube y deteccion de duplicados/pesados directos en Microsoft Graph.\n"
        "Seguridad: tokens cifrados localmente con Windows DPAPI."
    ),
    "storage_od_disconnect": (
        "Cierra la sesion OAuth de OneDrive Nube y borra los tokens locales cifrados de este PC."
    ),
    "storage_od_config": (
        "Configura el Client ID de Microsoft Entra ID y el tipo de cuenta para OneDrive Nube."
    ),
    # Processes View
    "proc_boost": (
        "Compacta Working Set y aplica modo Eficiencia (EcoQoS) a navegadores y apps pesadas en segundo plano.\n"
        "Mejora: libera RAM inmediatamente y reduce consumo energetico.\n"
        "Seguridad: no cierra apps ni toca tu ventana en primer plano ni editores/agentes IA."
    ),
    "proc_auto_ram": (
        "Activa o desactiva la intervencion automatica SRE cuando la RAM libre baja del umbral calibrado.\n"
        "Mejora: evita congelamientos cuando trabajas con multiples pestanas y herramientas IA.\n"
        "Seguridad: espera 3 muestras seguidas y respeta 5 minutos de enfriamiento."
    ),
    "proc_ecoqos": (
        "Incluye navegadores y apps Electron en segundo plano dentro del modo Eficiencia (EcoQoS) de Windows 11.\n"
        "Mejora: prioriza nucleos de eficiencia y reduce calor/bateria sin cerrar tus pestanas."
    ),
    "proc_refresh": (
        "Actualiza manualmente la lista de procesos activos (% CPU y RAM) y busca workers MCP huerfanos.\n"
        "Mejora: te muestra cambios inmediatos tras ejecutar AI Boost o cerrar apps."
    ),
    "proc_kill_zombie": (
        "Finaliza unicamente el proceso zombi seleccionado (Node/Python/uv cuyo proceso padre ya no existe).\n"
        "Mejora: recupera RAM atrapada por servidores MCP o scripts abandonados.\n"
        "Seguridad: bloqueado para cualquier proceso del sistema, IDE o agente activo."
    ),
    "proc_focus": (
        "Activa o revierte Modo Enfoque: aplica EcoQoS + prioridad de E/S muy baja a clutter y evita suspension.\n"
        "Mejora: protege tu ventana activa y tareas IA sin interrupciones de fondo.\n"
        "Seguridad: reversible en un clic devolviendo prioridades previas."
    ),
    "proc_standby": (
        "Depura la memoria cache en espera (Standby List) de Windows mediante NtSetSystemInformation (UAC).\n"
        "Mejora: recupera memoria cache estancada antes de abrir cargas pesadas o IA local.\n"
        "Seguridad: solo libera paginas inactivas en cache; no cierra aplicaciones."
    ),
    "proc_ecoqos_manual": (
        "Alterna Windows 11 EcoQoS (Modo Eficiencia) sobre los procesos seleccionados en la tabla.\n"
        "Seguridad: bloqueado para sistema, antivirus, instaladores y agentes IA."
    ),
    "proc_iolow_manual": (
        "Alterna prioridad de disco E/S muy baja (IOPRIO_VERYLOW) sobre los procesos seleccionados.\n"
        "Mejora: evita que respaldos o procesos secundarios frenen tu disco principal."
    ),
    # Thermal & BIOS View
    "thermal_audit": (
        "Ejecuta auditoria completa read-only de CPU, GPU, NVMe/S.M.A.R.T., eventos 14d, BIOS OEM y seguridad.\n"
        "Mejora: detecta discos con desgaste, drivers antiguos, BIOS > 2 anos o reinicios pendientes.\n"
        "Seguridad: solo consulta WMI/Registro; no aplica cambios sin tu clic."
    ),
    "thermal_uac_temp": (
        "Solicita elevacion puntual (UAC) para leer sensores termicos ACPI y NVMe protegidos por Windows.\n"
        "Mejora: muestra temperatura real en grados Celsius en Resumen y Termica.\n"
        "Seguridad: lectura puntual de sensores; no modifica configuraciones."
    ),
    "thermal_profile_cool": (
        "Reduce agresividad Turbo y sube EPP (65%) mediante powercfg oficial.\n"
        "Mejora: portatil mas frio, menos ruido de ventilador y mayor autonomia de bateria (sin reiniciar).\n"
        "Seguridad: respalda el plan de energia antes de aplicar."
    ),
    "thermal_profile_balanced": (
        "Equilibra respuesta rapida con ventilacion moderada (EPP 40%, Efficient Aggressive).\n"
        "Mejora: punto optimo para trabajo diario, ofimatica y desarrollo sin calor excesivo.\n"
        "Seguridad: se aplica en caliente y se verifica con powercfg /q."
    ),
    "thermal_profile_ai_local": (
        "Desbloquea frecuencia Turbo completa y EPP 15% para maxima velocidad de CPU/iGPU.\n"
        "Mejora: acelera compilaciones, analisis de datos pesados e inferencia IA local.\n"
        "Seguridad: usa parametros oficiales de Windows; reversible en 1 clic."
    ),
    "thermal_backups": (
        "Abre en el Explorador la carpeta donde se guardan respaldos .pow de energia y snapshots previos.\n"
        "Mejora: transparencia total y acceso rapido a cada punto de restauracion."
    ),
    "thermal_reset_pending": (
        "Vuelve a mostrar todas las recomendaciones de auditoria marcadas anteriormente como completadas.\n"
        "Mejora: util si deseas volver a ejecutar un mantenimiento (TRIM, CHKDSK o DISM)."
    ),
    "thermal_restore_power": (
        "Restaura el ultimo plan de energia .pow respaldado (o los planes de fabrica de Windows).\n"
        "Mejora: revierte cualquier ajuste termico en 1 clic si prefieres volver al estado original."
    ),
}

# ---------------------------------------------------------------------------
# Collapsible "Que mejora esta seccion?" strip data per view & storage mode
# ---------------------------------------------------------------------------
SECTION_BENEFITS: dict[str, dict[str, str]] = {
    "overview": {
        "title": "Que mejora esta vista (Resumen y Guardia SRE)",
        "improves": (
            "Vigila RAM, disco C:, CPU y temperatura con historial de 24 h / 7 d. "
            "'Ejecutar AI Boost' libera memoria inactiva al instante sin cerrar tus ventanas ni tu IDE."
        ),
        "safety": "Solo lectura continua; el Guardia SRE nunca borra archivos en disco automaticamente.",
    },
    "storage_junk": {
        "title": "Que mejora: Temporales y Caches",
        "improves": (
            "Elimina archivos temporales residuales, caches de navegadores (sin cerrar sesiones) y caches de "
            "Windows Update / uv / pip / npm / VS Code para recuperar gigabytes y acelerar el SSD."
        ),
        "safety": "Omite archivos bloqueados en uso y respalda lo movido en Cuarentena (auto-expira a los 30 dias).",
    },
    "storage_duplicates": {
        "title": "Que mejora: Duplicados BLAKE3",
        "improves": (
            "Detecta copias 100% identicas en tus documentos o descargas. Puedes enviar copias sobrantes a "
            "Cuarentena o usar 'Hardlink NTFS' para liberar espacio manteniendo ambos accesos."
        ),
        "safety": "Protege programas instalados, .venv, AppData, drivers y carpetas copiadas completas.",
    },
    "storage_tree": {
        "title": "Que mejora: Arbol, Mapa y Archivos Pesados",
        "improves": (
            "Visualiza en un mapa proporcional y top-100 exactamente que carpetas o formatos (videos, "
            "respaldos, bases de datos) ocupan tu disco para decidir con precision que limpiar."
        ),
        "safety": "Carga perezosa de baja RAM; nunca descarga archivos OneDrive solo-en-la-nube.",
    },
    "storage_orphans": {
        "title": "Que mejora: Archivos Huerfanos",
        "improves": (
            "Encuentra carpetas olvidadas de aplicaciones ya desinstaladas para limpiar basura oculta en AppData."
        ),
        "safety": "No borra nada automaticamente; todo elemento seleccionado pasa primero a Cuarentena.",
    },
    "storage_quarantine": {
        "title": "Que mejora: Boveda de Cuarentena",
        "improves": (
            "Te permite verificar que todo en tu PC sigue funcionando bien tras una limpieza antes de vaciar "
            "definitivamente la Boveda y liberar el espacio final en C:."
        ),
        "safety": "Restauracion integra con verificacion SHA-256 en 1 clic; nunca sobrescribe archivos nuevos.",
    },
    "storage_onedrive": {
        "title": "Que mejora: OneDrive Local y Nube",
        "improves": (
            "Convierte archivos locales antiguos en 'Solo en la nube' (Files On-Demand) para liberar espacio "
            "en SSD sin borrarlos, y detecta duplicados o pesados directamente en Microsoft Graph."
        ),
        "safety": "Protege repositorios .git/.venv, cifra tokens con DPAPI y usa la Papelera de OneDrive.",
    },
    "processes": {
        "title": "Que mejora esta vista (Procesos e IA Agentica)",
        "improves": (
            "Identifica que apps consumen mas RAM o % CPU, aplica Windows 11 EcoQoS en segundo plano y "
            "detecta procesos Node/Python/uv huerfanos (zombis) para recuperar memoria atrapada."
        ),
        "safety": "Protege automaticamente Windows, antivirus, OneDrive, ventana activa y agentes IA.",
    },
    "thermal": {
        "title": "Que mejora esta vista (Termica, BIOS y S.M.A.R.T.)",
        "improves": (
            "Reduce calor y ruido del portatil (o libera rendimiento maximo para IA local) sin reiniciar, "
            "revisa salud S.M.A.R.T. del SSD, eventos de disco 14d y reparaciones CHKDSK / DISM / SFC."
        ),
        "safety": "Respalda tu plan de energia (.pow) antes de cambiar perfiles y bloquea DISM si ya hay otro activo.",
    },
    "apps": {
        "title": "Que mejora esta vista (Administrador de Aplicaciones)",
        "improves": (
            "Detecta aplicaciones olvidadas segun su fecha real de ultimo uso, verifica nuevas versiones "
            "mediante Microsoft winget y desinstala programas con opcion segura de limpiar restos."
        ),
        "safety": "Protege componentes de Windows, antivirus, drivers y WinOptiAI; restos opcionales van a Cuarentena.",
    },
    "startup": {
        "title": "Que mejora esta vista (Inicio Inteligente de Windows)",
        "improves": (
            "Acelera el inicio de sesion y reduce la RAM ocupada al encender analizando que apps "
            "realmente usas y cuales solo consumen recursos en segundo plano."
        ),
        "safety": "Usa StartupApproved de Windows (100% reversible con 1 clic) y respalda cada cambio.",
    },
}

# ---------------------------------------------------------------------------
# Internal User Manual chapters shown inside AboutUpdaterDialog -> Manual tab
# ---------------------------------------------------------------------------
MANUAL_SECTIONS: list[dict[str, str]] = [
    {
        "id": "overview",
        "title": "1. Inicio y Guardia SRE",
        "body": (
            "OBJETIVO: Mantener tu equipo agil y monitoreado con consumo minimo (~45 MB RAM).\n\n"
            "- Tarjetas en vivo: muestran Memoria Fisica, Disco C:, CPU/Temperatura y estado SRE cada 2 s.\n"
            "- Graficos de Historial (24 h / 7 d): guardan 1 punto por minuto en metrics.sqlite y marcan "
            "eventos clave sobre la curva: [B] AI Boost, [L] Limpiezas, [D] Depuracion Boveda y [E] Errores.\n"
            "- Boton 'Ejecutar AI Boost': compacta paginas inactivas de RAM y activa EcoQoS en apps en "
            "segundo plano. No cierra ningun programa ni toca tu ventana activa.\n"
            "- Guardia SRE Automatico: calibra su umbral segun la RAM fisica del PC (1.2 a 4.0 GB). Solo "
            "actua tras 3 lecturas consecutivas bajo umbral y espera 5 minutos antes de volver a actuar.\n"
            "- Icono en bandeja: haz clic derecho junto al reloj para ver el perfil termico seleccionado, "
            "activar/pausar el Guardia SRE, cambiar de tema o ejecutar AI Boost en 1 clic."
        ),
    },
    {
        "id": "storage",
        "title": "2. Almacenamiento y Cuarentena",
        "body": (
            "OBJETIVO: Recuperar espacio en disco sin riesgo de perder archivos importantes.\n\n"
            "- Temporales y Caches: analiza %TEMP%, Windows\\Temp (con Admin UAC), caches de Chrome/Edge "
            "(conservando tus sesiones e historial), caches de uv/pip/npm/VS Code y descargas de Windows Update.\n"
            "- Casilla 'Seleccionar todo': selecciona o deselecciona todas las filas visibles en 1 clic.\n"
            "- Pausa / Guardar Pausa / Cancelar: en tareas largas puedes pausar o guardar la sesion para "
            "retomarla despues con 'Retomar Sesion', incluso tras reiniciar el equipo.\n"
            "- Cuarentena instantanea: pulsa la tecla Supr, usa el icono de caneca en cada fila o arrastra "
            "archivos desde el Explorador a 'Boveda Cuarentena'. Aparecera un aviso 'Deshacer' inmediato.\n"
            "- Boveda de Cuarentena: todo lo movido permanece recuperable con verificacion SHA-256. Para "
            "liberar definitivamente el espacio en C:, entra a Boveda y usa 'Purgar' o 'Vaciar todo'. "
            "Los lotes de Basura con mas de 30 dias se limpian automaticamente al iniciar."
        ),
    },
    {
        "id": "duplicates",
        "title": "3. Duplicados y Hardlinks",
        "body": (
            "OBJETIVO: Eliminar copias redundantes exactas sin danar instalaciones ni carpetas de trabajo.\n\n"
            "- Motor BLAKE3 en 4 etapas: compara tamano -> pre-hash 4 KB -> hash completo BLAKE3 -> inodo NTFS. "
            "Guarda huellas en hash_cache.sqlite para acelerar reescaneos.\n"
            "- Proteccion de programas: nunca recorre Program Files, AppData, ProgramData, C:\\Drivers, "
            ".venv, node_modules ni carpetas de instalacion (.exe + .dll). Ademas marca carpetas copiadas "
            "completas como protegidas.\n"
            "- Autolimpiar por Regla: elige conservar la copia mas antigua, mas reciente o de ruta mas corta; "
            "siempre conserva al menos 1 copia del usuario y pide confirmacion con resumen.\n"
            "- Hardlink NTFS: reemplaza duplicados en la misma particion por enlaces directos al mismo dato "
            "fisico (libera espacio sin que desaparezca el archivo en ninguna carpeta). Re-verifica tamano "
            "y BLAKE3 justo antes de enlazar."
        ),
    },
    {
        "id": "onedrive",
        "title": "4. OneDrive Local y Nube",
        "body": (
            "OBJETIVO: Liberar espacio en tu SSD y ordenar tu nube sin descargas accidentales.\n\n"
            "- Proteccion Cloud-Only global: en TODOS los analisis, WinOptiAI inspecciona atributos Win32 "
            "antes de leer un archivo para nunca descargar ni hidratar archivos 'Solo en la nube'.\n"
            "- Modo Local (Files On-Demand): detecta archivos pesados/inactivos ya sincronizados en OneDrive "
            "y los marca 'Solo en la nube' (+U -P) sin borrarlos. Protege automaticamente repositorios .git.\n"
            "- Modo Nube (Microsoft Graph OAuth PKCE): opcional; permite ver cuota real, hallar duplicados "
            "exactos por hash de nube sin descargar nada y enviar copias a la Papelera de OneDrive (30-93 dias). "
            "Los tokens se cifran localmente con Windows DPAPI."
        ),
    },
    {
        "id": "processes",
        "title": "5. Procesos IA y EcoQoS",
        "body": (
            "OBJETIVO: Mantener fluida la memoria y CPU cuando ejecutas IDEs, navegadores y agentes IA.\n\n"
            "- Tabla de procesos en vivo: ordenable por RAM, % CPU real (con cache de handles psutil), "
            "PID y estado EcoQoS.\n"
            "- Compactar RAM y EcoQoS: aplica modo eficiencia a navegadores y apps en segundo plano sin "
            "interrumpir tu ventana activa ni editores (VS Code, Antigravity, Claude, Python).\n"
            "- Cazador de Workers Zombis: detecta procesos node/python/uv inactivos cuyo proceso padre ya "
            "termino, permitiendote cerrarlos de forma selectiva."
        ),
    },
    {
        "id": "thermal",
        "title": "6. Termica, BIOS y S.M.A.R.T.",
        "body": (
            "OBJETIVO: Controlar temperatura/ruido y prevenir fallos de disco o sistema.\n\n"
            "- Perfiles Termicos (sin reiniciar): Frio/Silencioso (EPP 65%), Equilibrado Inteligente (EPP 40%) "
            "e IA Local Maxima (EPP 15% + Turbo completo). Cada cambio respalda tu plan .pow y verifica via powercfg /q.\n"
            "- Salud de Disco S.M.A.R.T. y Eventos 14d: reporta desgaste, temperatura NVMe y errores criticos "
            "Disk/Ntfs/WHEA en los ultimos 14 dias.\n"
            "- Acciones de mantenimiento 1-clic (UAC): TRIM SSD, CHKDSK C: /scan (en linea), DISM + SFC /scannow, "
            "limpieza WinSxS y desactivar Inicio Rapido. Si Windows tiene un reinicio pendiente, reinicia antes de DISM.\n"
            "- Auditoria BIOS OEM: avisa si la BIOS tiene mas de 2 anos y abre la utilidad oficial de tu marca "
            "(Lenovo Vantage, Dell, HP, ASUS). Nunca modifica NVRAM/BIOS directamente."
        ),
    },
    {
        "id": "apps",
        "title": "7. Aplicaciones y winget",
        "body": (
            "OBJETIVO: Mantener tu software al dia y eliminar programas que no usas sin dejar residuos.\n\n"
            "- Inventario con Ultimo Uso: lee Registro de Windows junto con BAM/Prefetch para mostrar cuando "
            "abriste realmente cada aplicacion por ultima vez.\n"
            "- Buscar Actualizaciones (winget): detecta versiones oficiales disponibles y permite actualizar "
            "de forma silenciosa en 1 clic.\n"
            "- Desinstalar y Limpiar Restos: ejecuta el desinstalador nativo (o winget) y luego ofrece revisar "
            "carpetas residuales en AppData para moverlas de forma reversible a Cuarentena."
        ),
    },
    {
        "id": "startup",
        "title": "8. Inicio Inteligente",
        "body": (
            "OBJETIVO: Lograr un arranque rapido y sin carga innecesaria segun tus habitos reales.\n\n"
            "- Semaforo Inteligente:\n"
            "  * MANTENER (verde): seguridad, antivirus, drivers de hardware, OneDrive o herramientas recientes.\n"
            "  * PAUSAR (ambar): apps de uso moderado o con consumo alto de RAM (>120 MB) que conviene abrir a mano.\n"
            "  * DESACTIVAR (rojo): apps opcionales de ocio/updaters o programas sin uso en >30 dias.\n"
            "- Reversibilidad total: los cambios usan StartupApproved (igual que el Administrador de Tareas) "
            "y siempre guardan respaldo previo en Backups."
        ),
    },
    {
        "id": "shortcuts",
        "title": "9. Atajos, Seguridad y Soporte",
        "body": (
            "ATAJOS UTILES:\n"
            "- Doble clic en cualquier fila de Almacenamiento: abre la carpeta en el Explorador de Windows.\n"
            "- Tecla Supr en tablas elegibles: mueve a Boveda de Cuarentena al instante con aviso 'Deshacer'.\n"
            "- Semaforo en Resumen: haz clic en RAM, Disco, Termica, Apps o Inicio para ir directo a cada vista.\n\n"
            "ACTUALIZACIONES Y ERRORES:\n"
            "- Auto-actualizador TRODAI: revisa GitHub Releases al iniciar (con reintento automatico si tarda "
            "el Wi-Fi) y cada 12 h; muestra aviso en ventana y globo clicable verificando SHA-256.\n"
            "- Diagnostico y Reporte: CrashGuard guarda crash.log localmente; nunca envia datos sin tu aprobacion."
        ),
    },
]
