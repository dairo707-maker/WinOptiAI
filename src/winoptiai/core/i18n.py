"""Internationalization module (ES / EN / PT) synced with Windows installer language."""

from __future__ import annotations

import locale

from .win32_bridge import IS_WINDOWS


SUPPORTED_LANGS: tuple[str, ...] = ("es", "en", "pt")

TRANSLATIONS: dict[str, dict[str, str]] = {
    "es": {
        "nav_overview": "Resumen",
        "nav_storage": "Almacenamiento",
        "nav_processes": "Procesos e IA",
        "nav_thermal": "Termica y BIOS",
        "nav_apps": "Aplicaciones",
        "nav_startup": "Inicio Windows",
        "nav_maintenance": "Mantenimiento",
        "btn_tour": "Tour y Prueba Rapida",
        "btn_about": "Acerca de y Actualizaciones",
        "btn_theme_dark": "Tema: Oscuro",
        "btn_theme_light": "Tema: Claro",
        "status_ready": "Sistema listo",
        "overview_title": "Resumen del Sistema",
        "overview_sub": "Telemetria en vivo · semaforo de salud · guardrails TRODAI SRE.",
        "btn_ai_boost": "AI Boost",
        "metric_ram": "RAM",
        "metric_disk": "Disco C:",
        "metric_cpu_temp": "CPU / Temp",
        "metric_sre": "SRE Auto",
        "audit_feed": "REGISTRO DE OPERACIONES Y TAREAS",
        "monitor_feed": "MONITOREO E HISTORIAL",
        "tab_history": "Historial y Graficas",
        "tab_freed": "Espacio liberado",
        "tab_audit": "Registro",
        "storage_title": "Gestor de Almacenamiento",
        "storage_sub": "Temporales, Duplicados BLAKE3, Arbol moderno y proteccion OneDrive.",
        "mode_junk": "Temporales y Caches",
        "mode_dups": "Duplicados BLAKE3",
        "mode_tree": "Arbol y Formatos",
        "mode_orphans": "Archivos Huerfanos",
        "mode_quarantine": "Boveda Cuarentena",
        "mode_onedrive": "OneDrive Nube",
        "select_all": "Seleccionar todo",
        "selected_count": "{n} de {total} seleccionados | {size}",
        "proc_title": "Procesos Activos e IA Agentica",
        "proc_sub": "Consumo en vivo, ultimo uso, EcoQoS y cierre seguro de workers zombis.",
        "thermal_title": "Termica, Tiempo Real y Auditoria",
        "thermal_sub": "Sensores CPU/NVMe, perfiles powercfg, S.M.A.R.T. y reparacion Windows.",
        "apps_title": "Administrador de Aplicaciones",
        "apps_sub": "Desinstala apps con seguridad y busca nuevas versiones via winget.",
        "startup_title": "Inicio de Windows Inteligente",
        "startup_sub": "Desactiva o pausa apps de arranque segun uso real (100% reversible).",
        "about_title": "Acerca de WinOptiAI · TRODAI",
        "about_author": "Producto de TRODAI · Autor: Dairo (dairo707-maker)",
        "about_check_updates": "Buscar Actualizaciones",
        "about_install_update": "Descargar e Instalar Actualizacion",
    },
    "en": {
        "nav_overview": "Overview",
        "nav_storage": "Storage",
        "nav_processes": "Processes & AI",
        "nav_thermal": "Thermal & BIOS",
        "nav_apps": "Applications",
        "nav_startup": "Startup Apps",
        "nav_maintenance": "Maintenance",
        "btn_tour": "Tour & Quick Check",
        "btn_about": "About & Updates",
        "btn_theme_dark": "Theme: Dark",
        "btn_theme_light": "Theme: Light",
        "status_ready": "System ready",
        "overview_title": "System Overview",
        "overview_sub": "Live telemetry · health semaphores · TRODAI SRE guardrails.",
        "btn_ai_boost": "AI Boost",
        "metric_ram": "RAM",
        "metric_disk": "Drive C:",
        "metric_cpu_temp": "CPU / Temp",
        "metric_sre": "Auto SRE",
        "audit_feed": "OPERATIONS & ACTIVE TASKS LOG",
        "monitor_feed": "MONITORING & HISTORY",
        "tab_history": "History & Charts",
        "tab_freed": "Space freed",
        "tab_audit": "Operations log",
        "storage_title": "Storage Manager",
        "storage_sub": "Temp caches, BLAKE3 duplicates, modern treemap, and OneDrive guard.",
        "mode_junk": "Temp & Caches",
        "mode_dups": "BLAKE3 Duplicates",
        "mode_tree": "Tree & Formats",
        "mode_orphans": "Orphan Files",
        "mode_quarantine": "Quarantine Vault",
        "mode_onedrive": "OneDrive Cloud",
        "select_all": "Select all",
        "selected_count": "{n} of {total} selected | {size}",
        "proc_title": "Active Processes & Agentic AI",
        "proc_sub": "Live OS processes, last used time, EcoQoS, and orphan MCP workers.",
        "thermal_title": "Thermal, Real-Time & Audit",
        "thermal_sub": "CPU/NVMe sensors, powercfg profiles, S.M.A.R.T., and system health.",
        "apps_title": "Application Manager",
        "apps_sub": "Safely uninstall user apps and check or install updates via winget.",
        "startup_title": "Smart Windows Startup",
        "startup_sub": "Reversibly disable or pause startup apps based on real usage.",
        "about_title": "About WinOptiAI · TRODAI",
        "about_author": "TRODAI Product · Author: Dairo (dairo707-maker)",
        "about_check_updates": "Check for Updates",
        "about_install_update": "Download & Install Update",
    },
    "pt": {
        "nav_overview": "Resumo",
        "nav_storage": "Armazenamento",
        "nav_processes": "Processos e IA",
        "nav_thermal": "Termica e BIOS",
        "nav_apps": "Aplicativos",
        "nav_startup": "Inicio Windows",
        "nav_maintenance": "Mantenimiento",
        "btn_tour": "Tour e Teste Rapido",
        "btn_about": "Sobre e Atualizacoes",
        "btn_theme_dark": "Tema: Escuro",
        "btn_theme_light": "Tema: Claro",
        "status_ready": "Sistema pronto",
        "overview_title": "Resumo do Sistema",
        "overview_sub": "Telemetria ao vivo · semaforo de saude · guardrails TRODAI SRE.",
        "btn_ai_boost": "AI Boost",
        "metric_ram": "RAM",
        "metric_disk": "Disco C:",
        "metric_cpu_temp": "CPU / Temp",
        "metric_sre": "Auto SRE",
        "audit_feed": "REGISTRO DE OPERACOES E TAREFAS",
        "monitor_feed": "MONITORAMENTO E HISTORICO",
        "tab_history": "Historico e Graficos",
        "tab_freed": "Espaco liberado",
        "tab_audit": "Registro",
        "storage_title": "Gestor de Armazenamento",
        "storage_sub": "Temporarios, Duplicados BLAKE3, arvore moderna e protecao OneDrive.",
        "mode_junk": "Temporarios e Caches",
        "mode_dups": "Duplicados BLAKE3",
        "mode_tree": "Arvore e Formatos",
        "mode_orphans": "Arquivos Orfaos",
        "mode_quarantine": "Cofre Quarentena",
        "mode_onedrive": "OneDrive Nuvem",
        "select_all": "Selecionar tudo",
        "selected_count": "{n} de {total} selecionados | {size}",
        "proc_title": "Processos Ativos e IA Agentica",
        "proc_sub": "Consumo ao vivo, ultimo uso, EcoQoS e workers MCP orfaos.",
        "thermal_title": "Termica, Tempo Real e Auditoria",
        "thermal_sub": "Sensores CPU/NVMe, perfis powercfg, S.M.A.R.T. e reparo Windows.",
        "apps_title": "Gerenciador de Aplicativos",
        "apps_sub": "Desinstale apps com seguranca e verifique atualizacoes via winget.",
        "startup_title": "Inicio Inteligente do Windows",
        "startup_sub": "Desative ou pause apps na inicializacao conforme uso real (reversivel).",
        "about_title": "Sobre o WinOptiAI · TRODAI",
        "about_author": "Produto da TRODAI · Autor: Dairo (dairo707-maker)",
        "about_check_updates": "Verificar Atualizacoes",
        "about_install_update": "Baixar e Instalar Atualizacao",
    },
}


def detect_default_language() -> str:
    """Detect language from Windows installer registry key or OS locale."""
    if IS_WINDOWS:
        try:
            import winreg

            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\WinOptiAI") as key:
                val, _ = winreg.QueryValueEx(key, "Language")
                if isinstance(val, str) and val[:2].lower() in SUPPORTED_LANGS:
                    return val[:2].lower()
        except OSError:
            pass

    loc = (locale.getlocale()[0] or "").lower()
    if loc.startswith("pt"):
        return "pt"
    if loc.startswith("en"):
        return "en"
    return "es"


def tr(key: str, lang: str = "es") -> str:
    """Lookup localized UI string with Spanish fallback."""
    table = TRANSLATIONS.get(lang, TRANSLATIONS["es"])
    return table.get(key, TRANSLATIONS["es"].get(key, key))
