from pathlib import Path

from yoke_core.tools import installer_live_tui_catalog as catalog
from yoke_core.tools import installer_live_tui_fleet as fleet


CATALOG = Path(__file__).resolve().parents[3] / "docs" / "INSTALLER-TESTING.md"
MODE_IDS = (
    "LOCAL-BIRTH-001",
    "MODE-PICKER-001",
    "MODE-PICKER-002",
    "MODE-PICKER-003",
    "SELF-HOST-001",
    "HOSTED-CONNECT-001",
    "HOSTED-GITHUB-001",
    "PORTABILITY-001",
    "PORTABILITY-002",
    "UPGRADE-001",
    "UPGRADE-002",
)


def test_public_launch_mode_wave_has_stable_executable_catalog_entries() -> None:
    scenarios = catalog.load_scenarios_from_plan(CATALOG)
    selected = [scenario for scenario in scenarios if scenario.scenario_id in MODE_IDS]

    assert tuple(scenario.scenario_id for scenario in selected) == MODE_IDS
    assert {scenario.wave for scenario in selected} == {
        "Wave 13: Open Source Mode Closing Regression"
    }
    assert {scenario.host_profile for scenario in selected} <= fleet.SUPPORTED_PROFILES
    for scenario in selected:
        assert "Post-apply:" in scenario.assertions
