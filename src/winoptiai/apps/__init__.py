"""User application manager (Registry + winget) and smart Windows startup optimizer."""

from __future__ import annotations

from .app_manager import (
    InstalledApp,
    check_app_updates_winget,
    find_app_leftovers,
    is_winget_available,
    list_installed_apps,
    parse_winget_upgrade_output,
    uninstall_installed_app,
    upgrade_app_winget,
)
from .startup_manager import (
    StartupItem,
    classify_startup_item,
    scan_startup_items,
    set_startup_item_enabled,
)

__all__ = [
    "InstalledApp",
    "StartupItem",
    "check_app_updates_winget",
    "classify_startup_item",
    "find_app_leftovers",
    "is_winget_available",
    "list_installed_apps",
    "parse_winget_upgrade_output",
    "scan_startup_items",
    "set_startup_item_enabled",
    "uninstall_installed_app",
    "upgrade_app_winget",
]
