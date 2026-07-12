from __future__ import annotations

from pathlib import Path

import pytest

from yoke_core.domain import json_helper
from yoke_core.tools import installer_live_tui_catalog as catalog
from yoke_core.tools import installer_live_tui_coordinator as coordinator


ROOT = Path(__file__).resolve().parents[3]
MAIN_CATALOG = ROOT / "docs" / "INSTALLER-TESTING.md"
GITHUB_CATALOG = ROOT / "docs" / catalog.GITHUB_APP_CATALOG_NAME
GITHUB_IDS = tuple(f"GITHUB-{number:03d}" for number in range(1, 54))


def test_main_catalog_composes_canonical_github_companion() -> None:
    main_text = MAIN_CATALOG.read_text(encoding="utf-8")
    scenarios = catalog.load_scenarios_from_plan(MAIN_CATALOG)

    github_scenarios = [
        scenario for scenario in scenarios if scenario.scenario_id.startswith("GITHUB-")
    ]
    assert "| `GITHUB-" not in main_text
    assert tuple(scenario.scenario_id for scenario in github_scenarios) == GITHUB_IDS
    assert {scenario.wave for scenario in github_scenarios} == {
        "Wave 5: Machine GitHub App Connection"
    }
    assert scenarios == catalog.load_scenarios_from_plan(MAIN_CATALOG)


def test_composed_catalog_rejects_duplicate_ids(tmp_path: Path) -> None:
    table = """
### Wave 5: Machine GitHub App Connection

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `GITHUB-001` | `prepared-yoke` | Skip | remains local |
""".strip()
    main = tmp_path / "INSTALLER-TESTING.md"
    main.write_text(table, encoding="utf-8")
    (tmp_path / catalog.GITHUB_APP_CATALOG_NAME).write_text(table, encoding="utf-8")

    with pytest.raises(ValueError, match="duplicate scenario ids: GITHUB-001"):
        catalog.load_scenarios_from_plan(main)


def test_github_app_catalog_rows_remain_operator_attended(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign"
    recipe_dir = campaign_root / "recipe-stubs"
    recipe_dir.mkdir(parents=True)
    for scenario_id in GITHUB_IDS:
        json_helper.dump_path(
            recipe_dir / f"{scenario_id}.json",
            {
                "scenario_id": scenario_id,
                "status": "blocked",
                "blocked_reason": "manual App fixture is required",
                "host_profile": (
                    "prepared-yoke"
                    if scenario_id == "GITHUB-001"
                    else "fault-injection"
                ),
                "actions": [],
                "expected_text": [],
            },
        )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert set(GITHUB_IDS) <= coordinator.KNOWN_RECIPE_IDS
    assert set(GITHUB_IDS[1:]) <= coordinator.MANUAL_GITHUB_APP_RECIPE_IDS
    assert [item["scenario_id"] for item in result["seeded"]] == ["GITHUB-001"]
    assert {item["scenario_id"] for item in result["unseeded"]} == set(GITHUB_IDS[1:])
    assert all(
        "HTTPS device-flow and installation fixture" in item["reason"]
        for item in result["unseeded"]
    )


def test_live_guide_does_not_claim_manual_rows_are_automated() -> None:
    normalized = " ".join(GITHUB_CATALOG.read_text(encoding="utf-8").split())

    assert "`GITHUB-002` through `GITHUB-053`" in normalized
    assert "A blocked recipe stub is not a pass" in normalized
