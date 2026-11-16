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
        "btn_about": "Acerca de y Actualizaciones",
        "btn_theme_dark": "Tema: Oscuro",
        "btn_theme_light": "Tema: Claro",
        "status_ready": "Sistema listo",
        "overview_title": "Estado del Sistema",
        "overview_sub": "Telemetria en vivo, frecuencia CPU, temperatura y guardrails SRE para IA.",
        "btn_ai_boost": "Ejecutar AI Boost",
        "metric_ram": "Memoria Fisica",
        "metric_disk": "Almacenamiento",
        "metric_cpu_temp": "CPU y Termica",
        "metric_sre": "Guardia SRE",
        "audit_feed": "REGISTRO DE OPERACIONES Y TAREAS",
        "storage_title": "Gestor de Almacenamiento",
        "storage_sub": "Proteccion OneDrive Cloud-Only, Restart Manager, vista jerarquica y duplicados BLAKE3.",
        "mode_junk": "Temporales y Caches",
        "mode_dups": "Duplicados BLAKE3",
        "mode_tree": "Arbol y Formatos",
        "mode_orphans": "Archivos Huerfanos",
        "mode_quarantine": "Boveda Cuarentena",
        "proc_title": "Procesos Activos e IA Agentica",
        "proc_sub": "Procesos del sistema en vivo, tareas activas, EcoQoS y workers MCP huerfanos.",
        "thermal_title": "Termica, Tiempo Real y Auditoria Universal",
        "thermal_sub": "Perfilador multi-hardware (Intel/AMD/NVIDIA), sensores en vivo y acciones recomendadas.",
        "about_title": "Acerca de WinOptiAI",
        "about_author": "Autor y creditos: Dairo (dairo707-maker)",
        "about_check_updates": "Buscar Actualizaciones",
        "about_install_update": "Descargar e Instalar Actualizacion",
    },
    "en": {
        "nav_overview": "Overview",
        "nav_storage": "Storage",
        "nav_processes": "Processes & AI",
        "nav_thermal": "Thermal & BIOS",
        "btn_about": "About & Updates",
        "btn_theme_dark": "Theme: Dark",
        "btn_theme_light": "Theme: Light",
        "status_ready": "System ready",
        "overview_title": "System Overview",
        "overview_sub": "Live telemetry, CPU clock, temperature, and SRE guardrails for agentic AI.",
        "btn_ai_boost": "Run AI Boost",
        "metric_ram": "Physical Memory",
        "metric_disk": "Storage",
        "metric_cpu_temp": "CPU & Thermal",
        "metric_sre": "SRE Guardrail",
        "audit_feed": "OPERATIONS & ACTIVE TASKS LOG",
        "storage_title": "Storage Manager",
        "storage_sub": "OneDrive Cloud-Only protection, Restart Manager, folder hierarchy, and BLAKE3 duplicates.",
        "mode_junk": "Temp & Caches",
        "mode_dups": "BLAKE3 Duplicates",
        "mode_tree": "Tree & Formats",
        "mode_orphans": "Orphan Files",
        "mode_quarantine": "Quarantine Vault",
        "proc_title": "Active Processes & Agentic AI",
        "proc_sub": "Live OS processes, active tasks, Windows 11 EcoQoS, and orphan MCP workers.",
        "thermal_title": "Thermal, Real-Time & Hardware Audit",
        "thermal_sub": "Universal hardware profiler (Intel/AMD/NVIDIA), live sensors, and one-click fixes.",
        "about_title": "About WinOptiAI",
        "about_author": "Author & credits: Dairo (dairo707-maker)",
        "about_check_updates": "Check for Updates",
        "about_install_update": "Download & Install Update",
    },
    "pt": {
        "nav_overview": "Resumo",
        "nav_storage": "Armazenamento",
        "nav_processes": "Processos e IA",
        "nav_thermal": "Termica e BIOS",
        "btn_about": "Sobre e Atualizacoes",
        "btn_theme_dark": "Tema: Escuro",
        "btn_theme_light": "Tema: Claro",
        "status_ready": "Sistema pronto",
        "overview_title": "Estado do Sistema",
        "overview_sub": "Telemetria em tempo real, frequencia CPU, temperatura e guardrails SRE para IA.",
        "btn_ai_boost": "Executar AI Boost",
        "metric_ram": "Memoria Fisica",
        "metric_disk": "Armazenamento",
        "metric_cpu_temp": "CPU e Termica",
        "metric_sre": "Guarda SRE",
        "audit_feed": "REGISTRO DE OPERACOES E TAREFAS",
        "storage_title": "Gestor de Armazenamento",
        "storage_sub": "Protecao OneDrive Cloud-Only, Restart Manager, arvore de pastas e duplicados BLAKE3.",
        "mode_junk": "Temporarios e Caches",
        "mode_dups": "Duplicados BLAKE3",
        "mode_tree": "Arvore e Formatos",
        "mode_orphans": "Arquivos Orfaos",
        "mode_quarantine": "Cofre Quarentena",
        "proc_title": "Processos Ativos e IA Agentica",
        "proc_sub": "Processos ativos do sistema, tarefas em execucao, EcoQoS e workers MCP orfaos.",
        "thermal_title": "Termica, Tempo Real e Auditoria",
        "thermal_sub": "Perfilador universal de hardware (Intel/AMD/NVIDIA), sensores ao vivo e correcoes.",
        "about_title": "Sobre o WinOptiAI",
        "about_author": "Autor e creditos: Dairo (dairo707-maker)",
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
