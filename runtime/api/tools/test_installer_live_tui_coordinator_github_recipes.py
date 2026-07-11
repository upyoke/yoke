"""GitHub recipe coverage for the live installer campaign coordinator."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain import json_helper
from yoke_core.tools import installer_live_tui_coordinator as coordinator


def test_seed_known_recipes_adds_github_wave_recipes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    stage_token = tmp_path / "stage.token"
    stage_token.write_text("stage-token\n", encoding="utf-8")
    monkeypatch.setattr(coordinator, "REMOTE_STAGE_TOKEN_PATH", str(stage_token))
    campaign_root = tmp_path / "campaign"
    recipe_dir = campaign_root / "recipe-stubs"
    recipe_dir.mkdir(parents=True)
    profiles = {
        **{f"GITHUB-{number:03d}": "prepared-yoke" for number in range(1, 25)},
        **{
            f"GITHUB-{number:03d}": "prepared-stored-state"
            for number in (5, 6, 9, 10, 15, 23, 24)
        },
        **{
            f"GITHUB-{number:03d}": "fault-injection"
            for number in (3, 10, 14, 21, 22)
        },
        **{
            f"GITHUB-{number:03d}": "prepared-git"
            for number in range(16, 20)
        },
    }
    for scenario_id, profile in profiles.items():
        json_helper.dump_path(
            recipe_dir / f"{scenario_id}.json",
            {
                "scenario_id": scenario_id,
                "status": "blocked",
                "blocked_reason": "manual App fixture is required",
                "host_profile": profile,
                "actions": [],
                "expected_text": [],
            },
        )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["seeded_count"] == 1
    assert result["unseeded_count"] == 23
    assert [item["scenario_id"] for item in result["seeded"]] == ["GITHUB-001"]
    assert {item["scenario_id"] for item in result["unseeded"]} == {
        f"GITHUB-{number:03d}" for number in range(2, 25)
    }
    assert all(
        "HTTPS device-flow and installation fixture" in item["reason"]
        for item in result["unseeded"]
    )

    skip = json_helper.load_path(recipe_dir / "GITHUB-001.json")
    assert isinstance(skip, dict)
    assert skip["status"] == "ready"
    assert "path fix --yes" in skip["command"]
    assert skip["stage_files"] == [
        {"source_path": str(stage_token), "remote_path": str(stage_token)}
    ]
    assert skip["actions"][-2:] == [
        {"step": "060-github-skip-option", "keys": ["Down"]},
        {"step": "061-project-mode", "keys": ["Enter"]},
    ]
    assert "Connect GitHub?" in skip["expected_text"]
    assert "Use backlog only" in skip["expected_text"]

    for scenario_id in sorted(set(profiles) - {"GITHUB-001"}):
        recipe = json_helper.load_path(recipe_dir / f"{scenario_id}.json")
        assert recipe["status"] == "blocked"
        assert recipe["blocked_reason"] == "manual App fixture is required"
