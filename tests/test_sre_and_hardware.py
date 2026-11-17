"""Tests for SRE hybrid policy hysteresis, hardware/BIOS audit, SVG/no-emoji compliance."""

from __future__ import annotations

from pathlib import Path
import re

from winoptiai import get_base_dir, get_version
from winoptiai.ai_optimizer.process_manager import get_memory_snapshot
from winoptiai.core.sre_policy import SREPolicyConfig, SREPolicyEngine
from winoptiai.thermal_bios.bios_auditor import run_hardware_bios_audit
from winoptiai.thermal_bios.thermal_controller import THERMAL_PROFILES, get_active_power_scheme


def test_sre_policy_hysteresis_and_audit(tmp_path: Path) -> None:
    engine = SREPolicyEngine(app_dir=tmp_path)
    engine.save_config(
        SREPolicyConfig(
            auto_ram_relief_enabled=True,
            ram_threshold_gb=1.8,
            hysteresis_seconds=300,
            consecutive_breaches_required=3,
        )
    )

    # Needs 3 consecutive samples below 1.8 GB
    assert not engine.evaluate_ram_pressure(1.5, now=1000.0)
    assert not engine.evaluate_ram_pressure(1.4, now=1002.0)
    assert engine.evaluate_ram_pressure(1.3, now=1004.0)

    # Within 300s hysteresis window, must NOT re-trigger
    assert not engine.evaluate_ram_pressure(1.1, now=1010.0)
    assert not engine.evaluate_ram_pressure(1.1, now=1012.0)
    assert not engine.evaluate_ram_pressure(1.1, now=1014.0)

    # After cooldown expires, 3 breaches trigger again
    assert not engine.evaluate_ram_pressure(1.2, now=1320.0)
    assert not engine.evaluate_ram_pressure(1.2, now=1322.0)
    assert engine.evaluate_ram_pressure(1.2, now=1324.0)

    engine.record_audit_event("test", "AI Boost", "Ok", 250.5)
    rows = engine.read_recent_audit()
    assert len(rows) == 1
    assert rows[0]["freed_mb"] == 250.5


def test_hardware_audit_and_power_scheme() -> None:
    snap = get_memory_snapshot()
    assert snap["total_gb"] > 4.0

    guid, name = get_active_power_scheme()
    assert guid
    assert name
    assert set(THERMAL_PROFILES.keys()) == {"cool", "balanced", "ai_local"}

    report = run_hardware_bios_audit()
    assert report.bios_version != "N/D"
    assert report.disk_total_gb > 10.0


def test_assets_and_zero_emoji_ui_policy() -> None:
    base = get_base_dir()
    assert get_version() == "0.5.4"
    assert (base / "assets" / "fonts" / "InstrumentSans.ttf").exists()
    assert (base / "assets" / "fonts" / "IBMPlexMono-Regular.ttf").exists()

    svg_dir = base / "assets" / "icons"
    for name in (
        "brand",
        "overview",
        "storage",
        "process",
        "thermal",
        "shield",
        "bell",
        "close",
        "folder",
        "sun",
        "moon",
    ):
        assert (svg_dir / f"{name}.svg").exists()

    # Enforce strict zero-emoji rule across all Python UI modules
    emoji_re = re.compile(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]")
    for py_file in (base / "src" / "winoptiai").rglob("*.py"):
        text = py_file.read_text(encoding="utf-8")
        assert not emoji_re.search(text), f"Emoji prohibido detectado en {py_file}"
