"""Official Windows powercfg thermal & processor boost controller.

Manages Intel Tiger Lake (i5-1135G7) heat generation without disabling Secure Boot
or modifying risky kernel drivers/MSR registers:
- Uses official Windows 11 Power Subgroup GUIDs (SUB_PROCESSOR)
- Adjusts PERFBOOSTMODE and PERFEPP (Energy Performance Preference)
- Supports 3 curated profiles: "cool", "balanced", "ai_local"
"""

from __future__ import annotations

from dataclasses import dataclass
import subprocess

from ..core.win32_bridge import IS_WINDOWS


SUB_PROCESSOR = "54533251-82be-4824-96c1-47b60b740d00"
PERFBOOSTMODE = "be337238-0d82-4146-a960-4f3749d470c7"
PERFEPP = "36687f9e-e3a5-4dbf-b1dc-15eb381c6863"
PROCTHROTTLEMAX = "bc5038f7-23e0-4960-96da-33abaf5935ec"
PROCTHROTTLEMIN = "893dee8e-2bef-41e0-89c6-b55d0929964c"


@dataclass(frozen=True, slots=True)
class ThermalProfile:
    """Declarative Windows processor thermal policy."""

    key: str
    title: str
    subtitle: str
    boost_mode_ac: int   # 0=Disabled, 3=Efficient Enabled, 4=Efficient Aggressive, 2=Aggressive
    boost_mode_dc: int
    epp_ac: int          # 0 (max perf) .. 100 (max efficiency/cool)
    epp_dc: int
    max_state_ac: int
    max_state_dc: int


THERMAL_PROFILES: dict[str, ThermalProfile] = {
    "cool": ThermalProfile(
        key="cool",
        title="Frio / Silencioso",
        subtitle="Controla picos termicos en sesiones largas de IA online (-12 a -18 C).",
        boost_mode_ac=3,  # Efficient Enabled
        boost_mode_dc=0,  # Disabled on battery
        epp_ac=65,
        epp_dc=80,
        max_state_ac=99,
        max_state_dc=85,
    ),
    "balanced": ThermalProfile(
        key="balanced",
        title="Equilibrado Inteligente",
        subtitle="Balance optimo entre compilacion rapida y ventilador moderado.",
        boost_mode_ac=4,  # Efficient Aggressive
        boost_mode_dc=3,
        epp_ac=40,
        epp_dc=60,
        max_state_ac=100,
        max_state_dc=95,
    ),
    "ai_local": ThermalProfile(
        key="ai_local",
        title="IA Local Maxima",
        subtitle="Desbloquea frecuencia Turbo completa para inferencia CPU / Iris Xe.",
        boost_mode_ac=2,  # Aggressive
        boost_mode_dc=3,
        epp_ac=15,
        epp_dc=40,
        max_state_ac=100,
        max_state_dc=100,
    ),
}


def _run_powercfg(args: list[str]) -> tuple[bool, str]:
    if not IS_WINDOWS:
        return False, "No disponible fuera de Windows"
    creation_flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    try:
        res = subprocess.run(
            ["powercfg", *args],
            capture_output=True,
            text=True,
            encoding="oem",
            errors="replace",
            timeout=8,
            creationflags=creation_flags,
        )
        out = (res.stdout or res.stderr or "").strip()
        return res.returncode == 0, out
    except (OSError, subprocess.SubprocessError) as exc:
        return False, str(exc)


def get_active_power_scheme() -> tuple[str, str]:
    """Return (guid, friendly_name) of the currently active Windows power plan."""
    ok, out = _run_powercfg(["/getactivescheme"])
    if not ok or ":" not in out:
        return "SCHEME_CURRENT", "Equilibrado"
    # Example: GUID de plan de energia: 381b4222-...  (Equilibrado)
    after_colon = out.split(":", 1)[1].strip()
    parts = after_colon.split(None, 1)
    guid = parts[0] if parts else "SCHEME_CURRENT"
    name = parts[1].strip("() ") if len(parts) > 1 else "Plan activo"
    return guid, name


def apply_thermal_profile(profile_key: str) -> tuple[bool, str]:
    """Apply one of the curated thermal profiles to the active Windows power scheme."""
    profile = THERMAL_PROFILES.get(profile_key)
    if profile is None:
        return False, f"Perfil termico desconocido: {profile_key}"

    commands = [
        ["/setacvalueindex", "SCHEME_CURRENT", SUB_PROCESSOR, PERFBOOSTMODE, str(profile.boost_mode_ac)],
        ["/setdcvalueindex", "SCHEME_CURRENT", SUB_PROCESSOR, PERFBOOSTMODE, str(profile.boost_mode_dc)],
        ["/setacvalueindex", "SCHEME_CURRENT", SUB_PROCESSOR, PERFEPP, str(profile.epp_ac)],
        ["/setdcvalueindex", "SCHEME_CURRENT", SUB_PROCESSOR, PERFEPP, str(profile.epp_dc)],
        ["/setacvalueindex", "SCHEME_CURRENT", SUB_PROCESSOR, PROCTHROTTLEMAX, str(profile.max_state_ac)],
        ["/setdcvalueindex", "SCHEME_CURRENT", SUB_PROCESSOR, PROCTHROTTLEMAX, str(profile.max_state_dc)],
        ["/setactive", "SCHEME_CURRENT"],
    ]

    for cmd in commands:
        ok, msg = _run_powercfg(cmd)
        if not ok:
            return False, f"Error en powercfg {' '.join(cmd)}: {msg}"

    # Read back EPP index to verify Windows power policy accepted the update
    q_ok, q_out = _run_powercfg(["/q", "SCHEME_CURRENT", SUB_PROCESSOR, PERFEPP])
    verified = "verificado" if q_ok and f"0x{profile.epp_ac:08x}" in q_out.lower() else "aplicado"
    return True, f"Perfil termico '{profile.title}' {verified} (EPP AC {profile.epp_ac}%)"


def restore_default_power_scheme() -> tuple[bool, str]:
    """Reset the active power plan to Windows factory defaults."""
    ok, msg = _run_powercfg(["/restoredefaultschemes"])
    if not ok:
        return False, f"No se pudo restaurar el plan por defecto: {msg}"
    return True, "Planes de energia restaurados a valores de fabrica de Windows"
