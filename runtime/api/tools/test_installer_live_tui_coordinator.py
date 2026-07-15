from __future__ import annotations

import threading
import time
from pathlib import Path

from yoke_core.domain import json_helper
from yoke_core.tools import installer_live_tui_capture as capture
from yoke_core.tools import installer_live_tui_coordinator as coordinator


class FakeRunner:
    def __init__(self, captures: list[str]) -> None:
        self.captures = captures
        self.calls: list[list[str]] = []

    def run(self, argv, *, env=None, timeout=30):  # noqa: ANN001, ANN201
        del env, timeout
        args = list(argv)
        self.calls.append(args)
        command = args[-1]
        if "capture-pane" in command:
            return capture.CommandResult(0, self.captures.pop(0), "")
        return capture.CommandResult(0, "", "")


def test_assign_hosts_writes_plan_and_reports_blocked_profiles(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign"
    _write_assignment(campaign_root, "A001", "bare-no-uv", ["INSTALL-SMOKE-001"])
    _write_assignment(campaign_root, "A002", "prepared-git", ["PROJECT-SOURCE-005"])
    ledger_path = _write_ledger(tmp_path, profile="bare-no-uv")

    result = coordinator.assign_hosts(
        campaign_root=campaign_root,
        ledger_path=ledger_path,
    )

    assert result["ok"] is False
    assert result["assigned_count"] == 1
    assert result["blocked_count"] == 1
    assert result["assigned"][0]["assignment_id"] == "A001"
    assert result["blocked"][0]["assignment_id"] == "A002"
    written = json_helper.load_path(campaign_root / "coordinator-plan.json")
    assert written == result


def test_plan_campaign_writes_bundle_demands_and_recipe_blockers(
    tmp_path: Path,
) -> None:
    plan_path = _write_strategy_plan(tmp_path)
    campaign_root = tmp_path / "campaign"

    result = coordinator.plan_campaign(
        plan_path=plan_path,
        campaign_root=campaign_root,
        assignment_size=1,
        slots_per_host=2,
    )

    assert result["campaign_executable"] is False
    assert result["scenario_count"] == 3
    assert result["mac_scenario_count"] == 1
    assert result["assignment_count"] == 3
    assert result["recipe_stub_count"] == 3
    assert result["recipe_blocker_count"] == 3
    assert (campaign_root / "harness-manifest.json").is_file()
    assert (campaign_root / "campaign-plan.json").is_file()
    assert (campaign_root / "recipe-stubs" / "INSTALL-SMOKE-001.json").is_file()
    demands = {item["profile"]: item for item in result["profile_demands"]}
    assert demands["bare-no-uv"]["assignment_count"] == 2
    assert demands["bare-no-uv"]["host_count"] == 1
    assert demands["prepared-git"]["host_count"] == 1
    stub = json_helper.load_path(
        campaign_root / "recipe-stubs" / "INSTALL-SMOKE-001.json"
    )
    assert isinstance(stub, dict)
    assert stub["status"] == "blocked"
    assert "exact key/action recipe" in stub["blocked_reason"]
    assert "api.stage.upyoke.com/install" in stub["launch_command_hint"]


def test_plan_campaign_preserves_ready_recipe_content(tmp_path: Path) -> None:
    plan_path = _write_strategy_plan(tmp_path)
    campaign_root = tmp_path / "campaign"
    recipe_dir = campaign_root / "recipe-stubs"
    recipe_dir.mkdir(parents=True)
    json_helper.dump_path(
        recipe_dir / "INSTALL-SMOKE-001.json",
        {
            "scenario_id": "INSTALL-SMOKE-001",
            "status": "ready",
            "command": "TERM=xterm-256color yoke onboard",
            "actions": [{"step": "000-initial"}],
            "expected_text": ["Set up your machine"],
            "post_checks": ["secret_free"],
            "stage_files": [
                {"source_path": str(tmp_path / "token"), "remote_path": "/tmp/token"}
            ],
            "execution_mode": "ssh-command",
            "expected_return_codes": [1],
            "pane": "custom-pane",
            "start_delay": 5.0,
            "step_delay": 2.0,
        },
    )

    result = coordinator.plan_campaign(
        plan_path=plan_path,
        campaign_root=campaign_root,
        assignment_size=1,
    )

    assert result["recipe_blocker_count"] == 2
    stub = json_helper.load_path(
        campaign_root / "recipe-stubs" / "INSTALL-SMOKE-001.json"
    )
    assert isinstance(stub, dict)
    assert stub["status"] == "ready"
    assert stub["command"] == "TERM=xterm-256color yoke onboard"
    assert stub["actions"] == [{"step": "000-initial"}]
    assert stub["expected_text"] == ["Set up your machine"]
    assert stub["stage_files"] == [
        {"source_path": str(tmp_path / "token"), "remote_path": "/tmp/token"}
    ]
    assert stub["execution_mode"] == "ssh-command"
    assert stub["expected_return_codes"] == [1]
    assert stub["pane"] == "custom-pane"
    assert stub["start_delay"] == 5.0
    assert stub["step_delay"] == 2.0
    assert "blocked_reason" not in stub
    assert stub["host_profile"] == "bare-no-uv"


def test_seed_known_recipes_marks_grounded_installer_recipes_ready(
    tmp_path: Path,
) -> None:
    plan_path = _write_strategy_plan(tmp_path)
    campaign_root = tmp_path / "campaign"
    coordinator.plan_campaign(
        plan_path=plan_path,
        campaign_root=campaign_root,
        assignment_size=1,
    )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["seeded_count"] == 3
    assert result["unseeded_count"] == 0
    smoke = json_helper.load_path(
        campaign_root / "recipe-stubs" / "INSTALL-SMOKE-001.json"
    )
    assert isinstance(smoke, dict)
    assert smoke["status"] == "ready"
    assert "blocked_reason" not in smoke
    assert smoke["actions"] == [
        {"step": "000-consent-screen"},
        {"step": "010-accept-default", "keys": ["Enter"]},
    ]
    assert "api.stage.upyoke.com/install" in smoke["command"]
    assert "Yoke's only prerequisite" in smoke["expected_text"]
    yes = json_helper.load_path(
        campaign_root / "recipe-stubs" / "INSTALL-SMOKE-002.json"
    )
    assert isinstance(yes, dict)
    assert yes["status"] == "ready"
    assert "--yes" in yes["command"]
    assert "Run yoke onboard" in yes["expected_text"]
    project_source = json_helper.load_path(
        campaign_root / "recipe-stubs" / "PROJECT-SOURCE-005.json"
    )
    assert isinstance(project_source, dict)
    assert project_source["status"] == "ready"
    assert (
        "How do you want to copy recipe/main-source?" in project_source["expected_text"]
    )


def test_seed_known_recipes_preserves_ready_recipe_without_overwrite(
    tmp_path: Path,
) -> None:
    plan_path = _write_strategy_plan(tmp_path)
    campaign_root = tmp_path / "campaign"
    coordinator.plan_campaign(
        plan_path=plan_path,
        campaign_root=campaign_root,
        assignment_size=1,
    )
    path = campaign_root / "recipe-stubs" / "INSTALL-SMOKE-002.json"
    recipe = json_helper.load_path(path)
    assert isinstance(recipe, dict)
    recipe.update(
        {
            "status": "ready",
            "command": "custom command",
            "actions": [{"step": "custom"}],
            "expected_text": ["custom"],
        }
    )
    recipe.pop("blocked_reason", None)
    json_helper.dump_path(path, recipe)

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["skipped_ready_count"] == 1
    preserved = json_helper.load_path(path)
    assert isinstance(preserved, dict)
    assert preserved["command"] == "custom command"
    assert preserved["actions"] == [{"step": "custom"}]


def test_seed_known_recipes_pre_stages_no_curl_installer(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign"
    recipe_dir = campaign_root / "recipe-stubs"
    recipe_dir.mkdir(parents=True)
    json_helper.dump_path(
        recipe_dir / "INSTALL-UV-004.json",
        {
            "scenario_id": "INSTALL-UV-004",
            "status": "blocked",
            "blocked_reason": "exact key/action recipe is not authored",
            "host_profile": "bare-no-curl",
            "actions": [],
            "expected_text": [],
        },
    )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["seeded_count"] == 1
    recipe = json_helper.load_path(recipe_dir / "INSTALL-UV-004.json")
    assert isinstance(recipe, dict)
    assert recipe["status"] == "ready"
    assert recipe["execution_mode"] == "ssh-command"
    assert recipe["command"].startswith("YOKE_CHANNEL=latest")
    assert "curl -fsSL" not in recipe["command"]
    assert recipe["expected_return_codes"] == [1]
    assert recipe["stage_files"] == [
        {
            "source_url": "https://api.stage.upyoke.com/install",
            "remote_path": "/tmp/yoke-install",
        }
    ]
    assert recipe["expected_text"] == ["uv/uvx is required and curl is missing"]


def test_seed_known_recipes_uses_ssh_command_for_no_tty_pipe(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign"
    recipe_dir = campaign_root / "recipe-stubs"
    recipe_dir.mkdir(parents=True)
    json_helper.dump_path(
        recipe_dir / "INSTALL-UV-006.json",
        {
            "scenario_id": "INSTALL-UV-006",
            "status": "blocked",
            "blocked_reason": "exact key/action recipe is not authored",
            "host_profile": "bare-no-uv",
            "actions": [],
            "expected_text": [],
        },
    )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["seeded_count"] == 1
    recipe = json_helper.load_path(recipe_dir / "INSTALL-UV-006.json")
    assert isinstance(recipe, dict)
    assert recipe["status"] == "ready"
    assert recipe["execution_mode"] == "ssh-command"
    assert recipe["expected_return_codes"] == [1]
    assert recipe["command"].startswith("cat /tmp/yoke-install | ")
    assert recipe["command"].endswith(" sh")
    assert "/tmp/yoke-install --" not in recipe["command"]
    assert recipe["post_checks"] == [
        "secret_free",
        "no_text:Device not configured",
    ]


def test_seed_known_recipes_uses_ssh_command_for_fast_installer_recipes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    stage_token = tmp_path / "stage.token"
    prod_token = tmp_path / "prod.token"
    stage_token.write_text("stage-token\n", encoding="utf-8")
    prod_token.write_text("prod-token\n", encoding="utf-8")
    monkeypatch.setattr(coordinator, "REMOTE_STAGE_TOKEN_PATH", str(stage_token))
    monkeypatch.setenv(coordinator.PROD_TOKEN_FILE_ENV, str(prod_token))
    campaign_root = tmp_path / "campaign"
    recipe_dir = campaign_root / "recipe-stubs"
    recipe_dir.mkdir(parents=True)
    scenario_ids = {
        "INSTALL-SMOKE-002",
        "INSTALL-SMOKE-004",
        "INSTALL-SMOKE-005",
        "INSTALL-UV-002",
        "INSTALL-UV-005",
        "INSTALL-UV-007",
        "INSTALL-UV-008",
        "INSTALL-UV-009",
        "INSTALL-UV-012",
    }
    for scenario_id in scenario_ids:
        json_helper.dump_path(
            recipe_dir / f"{scenario_id}.json",
            {
                "scenario_id": scenario_id,
                "status": "blocked",
                "blocked_reason": "exact key/action recipe is not authored",
                "host_profile": "prepared-yoke",
                "actions": [],
                "expected_text": [],
            },
        )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["seeded_count"] == len(scenario_ids)
    for scenario_id in scenario_ids:
        recipe = json_helper.load_path(recipe_dir / f"{scenario_id}.json")
        assert isinstance(recipe, dict)
        assert recipe["execution_mode"] == "ssh-command"
    decline = json_helper.load_path(recipe_dir / "INSTALL-UV-002.json")
    assert isinstance(decline, dict)
    assert decline["expected_return_codes"] == [1]
    piped_yes = json_helper.load_path(recipe_dir / "INSTALL-UV-005.json")
    assert isinstance(piped_yes, dict)
    assert piped_yes["expected_return_codes"] == [0]
    assert "Run yoke onboard" in piped_yes["expected_text"]
    assert "no_text:Starting Yoke onboard" in piped_yes["post_checks"]


def test_seed_known_recipes_uses_token_file_for_machine_only_stage(
    tmp_path: Path,
    monkeypatch,
) -> None:
    token = tmp_path / "stage.token"
    token.write_text("yoke-token\n", encoding="utf-8")
    monkeypatch.setattr(coordinator, "REMOTE_STAGE_TOKEN_PATH", str(token))
    campaign_root = tmp_path / "campaign"
    recipe_dir = campaign_root / "recipe-stubs"
    recipe_dir.mkdir(parents=True)
    json_helper.dump_path(
        recipe_dir / "INSTALL-SMOKE-004.json",
        {
            "scenario_id": "INSTALL-SMOKE-004",
            "status": "blocked",
            "blocked_reason": "exact key/action recipe is not authored",
            "host_profile": "prepared-yoke",
            "actions": [],
            "expected_text": [],
        },
    )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["seeded_count"] == 1
    recipe = json_helper.load_path(recipe_dir / "INSTALL-SMOKE-004.json")
    assert isinstance(recipe, dict)
    assert recipe["status"] == "ready"
    assert "onboard --non-interactive --quick" in recipe["command"]
    assert "--project-mode machine-only" in recipe["command"]
    assert "--github-adoption" not in recipe["command"]
    assert recipe["stage_files"] == [
        {
            "source_path": str(token),
            "remote_path": str(token),
        }
    ]
    assert '"final_status": "done"' in recipe["expected_text"]
    assert '"env": "stage"' in recipe["expected_text"]


def test_seed_known_recipes_uses_token_file_for_machine_only_prod(
    tmp_path: Path,
    monkeypatch,
) -> None:
    token = tmp_path / "prod.token"
    token.write_text("prod-token\n", encoding="utf-8")
    monkeypatch.setenv(coordinator.PROD_TOKEN_FILE_ENV, str(token))
    campaign_root = tmp_path / "campaign"
    recipe_dir = campaign_root / "recipe-stubs"
    recipe_dir.mkdir(parents=True)
    json_helper.dump_path(
        recipe_dir / "INSTALL-SMOKE-005.json",
        {
            "scenario_id": "INSTALL-SMOKE-005",
            "status": "blocked",
            "blocked_reason": "exact key/action recipe is not authored",
            "host_profile": "prepared-yoke",
            "actions": [],
            "expected_text": [],
        },
    )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["seeded_count"] == 1
    recipe = json_helper.load_path(recipe_dir / "INSTALL-SMOKE-005.json")
    assert isinstance(recipe, dict)
    assert recipe["status"] == "ready"
    assert "--env prod" in recipe["command"]
    assert "--api-url https://api.upyoke.com" in recipe["command"]
    assert "--token-file /tmp/yoke-prod.token" in recipe["command"]
    assert recipe["stage_files"] == [
        {
            "source_path": str(token),
            "remote_path": "/tmp/yoke-prod.token",
        }
    ]
    assert '"final_status": "done"' in recipe["expected_text"]
    assert '"env": "prod"' in recipe["expected_text"]


def test_seed_known_recipes_adds_fault_installer_recipes(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign"
    recipe_dir = campaign_root / "recipe-stubs"
    recipe_dir.mkdir(parents=True)
    for scenario_id in ("INSTALL-UV-010", "INSTALL-UV-011"):
        json_helper.dump_path(
            recipe_dir / f"{scenario_id}.json",
            {
                "scenario_id": scenario_id,
                "status": "blocked",
                "blocked_reason": "exact key/action recipe is not authored",
                "host_profile": "fault-injection",
                "actions": [],
                "expected_text": [],
            },
        )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["seeded_count"] == 2
    bad_channel = json_helper.load_path(recipe_dir / "INSTALL-UV-010.json")
    assert isinstance(bad_channel, dict)
    assert bad_channel["status"] == "ready"
    assert bad_channel["execution_mode"] == "ssh-command"
    assert bad_channel["expected_return_codes"] == [1]
    assert "YOKE_CHANNEL=yoke-missing-channel" in bad_channel["command"]
    assert "--yes --no-onboard" in bad_channel["command"]
    assert "yoke-missing-channel" in bad_channel["expected_text"]
    assert "no_text:Traceback" in bad_channel["post_checks"]

    dead_index = json_helper.load_path(recipe_dir / "INSTALL-UV-011.json")
    assert isinstance(dead_index, dict)
    assert dead_index["status"] == "ready"
    assert dead_index["execution_mode"] == "ssh-command"
    assert dead_index["expected_return_codes"] == [1]
    assert "/dist/install.py" in dead_index["command"]
    assert "--base-url http://127.0.0.1:9" in dead_index["command"]
    assert "--version 0.0.0" in dead_index["command"]
    assert "127.0.0.1:9" in dead_index["expected_text"]
    assert "no_text:Traceback" in dead_index["post_checks"]


def test_seed_known_recipes_adds_plain_terminal_installer_recipe(
    tmp_path: Path,
) -> None:
    campaign_root = tmp_path / "campaign"
    recipe_dir = campaign_root / "recipe-stubs"
    recipe_dir.mkdir(parents=True)
    json_helper.dump_path(
        recipe_dir / "INSTALL-UV-012.json",
        {
            "scenario_id": "INSTALL-UV-012",
            "status": "blocked",
            "blocked_reason": "exact key/action recipe is not authored",
            "host_profile": "prepared-screen-term",
            "actions": [],
            "expected_text": [],
        },
    )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["seeded_count"] == 1
    recipe = json_helper.load_path(recipe_dir / "INSTALL-UV-012.json")
    assert isinstance(recipe, dict)
    assert recipe["status"] == "ready"
    assert "TERM=screen" in recipe["command"]
    assert "YOKE_INSTALL_FORCE_COLOR=0" in recipe["command"]
    assert "YOKE_INSTALL_FORCE_PLAIN=1" in recipe["command"]
    assert "--yes --no-onboard" in recipe["command"]
    assert recipe["expected_text"] == ["* Setting up Yoke", "* Yoke v"]
    assert "no_text:☀" in recipe["post_checks"]


def test_seed_known_recipes_adds_path_front_door_recipes(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign"
    recipe_dir = campaign_root / "recipe-stubs"
    recipe_dir.mkdir(parents=True)
    profiles = {
        "PATH-001": "prepared-path-broken",
        "PATH-002": "prepared-path-broken",
        "PATH-003": "prepared-path-broken",
        "PATH-004": "prepared-yoke",
        "PATH-005": "prepared-path-broken",
        "PATH-006": "prepared-path-broken",
        "PATH-007": "prepared-screen-term",
        "PATH-008": "prepared-yoke",
    }
    for scenario_id, profile in profiles.items():
        json_helper.dump_path(
            recipe_dir / f"{scenario_id}.json",
            {
                "scenario_id": scenario_id,
                "status": "blocked",
                "blocked_reason": "exact key/action recipe is not authored",
                "host_profile": profile,
                "actions": [],
                "expected_text": [],
            },
        )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["seeded_count"] == 8
    path_add = json_helper.load_path(recipe_dir / "PATH-001.json")
    assert isinstance(path_add, dict)
    assert path_add["status"] == "ready"
    assert path_add["command"] == '"$HOME/.local/bin/yoke" onboard --post-install'
    assert path_add["actions"][-1] == {
        "step": "020-path-verified",
        "keys": ["Enter"],
    }
    assert "Added Yoke to your PATH." in path_add["expected_text"]

    preview = json_helper.load_path(recipe_dir / "PATH-002.json")
    assert isinstance(preview, dict)
    assert preview["actions"][2] == {
        "step": "020-path-preview",
        "keys": ["Down", "Enter"],
    }
    assert "BEGIN YOKE MANAGED PATH" in preview["expected_text"]
    assert "Wrote the managed block" in preview["expected_text"]
    assert "Your next terminal will find Yoke." in preview["expected_text"]
    assert "What Yoke adds to your shell files." not in preview["expected_text"]

    skip = json_helper.load_path(recipe_dir / "PATH-003.json")
    assert isinstance(skip, dict)
    assert skip["actions"][-1]["keys"] == ["Down", "Down", "Enter"]
    assert "Where should this Yoke live?" in skip["expected_text"]

    all_clear = json_helper.load_path(recipe_dir / "PATH-004.json")
    assert isinstance(all_clear, dict)
    assert all_clear["actions"][-1] == {
        "step": "020-after-second-continue",
        "keys": ["Enter"],
    }
    assert "Continue to account setup" not in all_clear["expected_text"]
    assert "Connect to Yoke." in all_clear["expected_text"]

    rerun = json_helper.load_path(recipe_dir / "PATH-006.json")
    assert isinstance(rerun, dict)
    assert rerun["command"].count("path fix --yes") == 2
    assert "path fix --yes" in rerun["command"]
    assert "/tmp/yoke-path-rerun-first.out" in rerun["command"]
    assert "/tmp/yoke-path-rerun-second.out" in rerun["command"]
    assert "PATH-006 retained path fix evidence" in rerun["command"]
    assert "grep -m1 '^Applied\\.$'" in rerun["command"]
    assert "grep -H -c 'BEGIN YOKE MANAGED PATH'" in rerun["command"]
    assert rerun["actions"] == [
        {"step": "000-path-fix-evidence"},
        {"step": "010-path-all-clear", "keys": ["Enter"]},
        {"step": "020-destination-after-continue", "keys": ["Enter"]},
        {"step": "030-env-after-hosted-pick", "keys": ["Enter"]},
    ]
    assert "PATH-006 retained path fix evidence" in rerun["expected_text"]
    assert "managed block counts:" in rerun["expected_text"]
    assert ".bash_profile:1" in rerun["expected_text"]
    assert ".bashrc:1" in rerun["expected_text"]
    assert "Press Enter to continue to onboard" in rerun["expected_text"]
    assert "Connect to Yoke." in rerun["expected_text"]

    plain = json_helper.load_path(recipe_dir / "PATH-007.json")
    assert isinstance(plain, dict)
    assert "YOKE_ONBOARD_FORCE_PLAIN=1" in plain["command"]
    assert "Add Yoke to your PATH." in plain["expected_text"]
    assert "An SSH command sees:" in plain["expected_text"]
    assert "no_text:☀" in plain["post_checks"]
    assert "no_text:›" in plain["post_checks"]

    quit_recipe = json_helper.load_path(recipe_dir / "PATH-008.json")
    assert isinstance(quit_recipe, dict)
    assert quit_recipe["actions"][-1] == {
        "step": "010-after-quit",
        "keys": ["Down", "Enter"],
        "capture": False,
    }
    assert "tmux_exit_code:130" in quit_recipe["post_checks"]


def test_seed_known_recipes_adds_auth_wave_recipes(
    tmp_path: Path,
    monkeypatch,
) -> None:
    stage_token = tmp_path / "stage.token"
    prod_token = tmp_path / "prod.token"
    stage_token.write_text("stage-token\n", encoding="utf-8")
    prod_token.write_text("prod-token\n", encoding="utf-8")
    monkeypatch.setattr(coordinator, "REMOTE_STAGE_TOKEN_PATH", str(stage_token))
    monkeypatch.setenv(coordinator.PROD_TOKEN_FILE_ENV, str(prod_token))
    campaign_root = tmp_path / "campaign"
    recipe_dir = campaign_root / "recipe-stubs"
    recipe_dir.mkdir(parents=True)
    profiles = {
        "AUTH-001": "prepared-yoke",
        "AUTH-002": "prepared-yoke",
        "AUTH-003": "prepared-yoke",
        "AUTH-004": "prepared-yoke",
        "AUTH-005": "prepared-yoke",
        "AUTH-006": "prepared-yoke",
        "AUTH-007": "prepared-yoke",
        "AUTH-008": "fault-injection",
        "AUTH-009": "prepared-stored-state",
        "AUTH-010": "prepared-stored-state",
        "AUTH-011": "prepared-yoke",
    }
    for scenario_id, profile in profiles.items():
        json_helper.dump_path(
            recipe_dir / f"{scenario_id}.json",
            {
                "scenario_id": scenario_id,
                "status": "blocked",
                "blocked_reason": "exact key/action recipe is not authored",
                "host_profile": profile,
                "actions": [],
                "expected_text": [],
            },
        )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["seeded_count"] == 11
    assert result["unseeded_count"] == 0
    for scenario_id in profiles:
        recipe = json_helper.load_path(recipe_dir / f"{scenario_id}.json")
        assert isinstance(recipe, dict)
        assert recipe["status"] == "ready"

    stage = json_helper.load_path(recipe_dir / "AUTH-001.json")
    assert isinstance(stage, dict)
    assert stage["stage_files"] == [
        {"source_path": str(stage_token), "remote_path": str(stage_token)}
    ]
    assert stage["actions"][-1]["keys"] == [str(stage_token), "Enter"]
    assert "path fix --yes" in stage["command"]
    assert "Stage" in stage["expected_text"]
    assert "Yoke is already on your PATH." not in stage["expected_text"]

    prod = json_helper.load_path(recipe_dir / "AUTH-002.json")
    assert isinstance(prod, dict)
    assert prod["stage_files"] == [
        {"source_path": str(prod_token), "remote_path": "/tmp/yoke-prod.token"}
    ]
    assert prod["actions"][2]["keys"] == ["Enter"]
    assert "Production" in prod["expected_text"]

    custom = json_helper.load_path(recipe_dir / "AUTH-003.json")
    assert isinstance(custom, dict)
    assert "19087" in custom["command"]
    assert custom["actions"][2]["keys"] == ["Up", "Enter"]
    assert custom["actions"][3]["keys"] == [
        "http://127.0.0.1:19087",
        "Enter",
    ]
    assert "Projects: recipe-project (admin)" in custom["expected_text"]

    paste = json_helper.load_path(recipe_dir / "AUTH-004.json")
    assert isinstance(paste, dict)
    assert paste["actions"][-1]["keys"] == [
        f"paste_file:{stage_token}",
        "Enter",
    ]
    assert "Paste your Yoke API token." in paste["expected_text"]

    missing = json_helper.load_path(recipe_dir / "AUTH-005.json")
    assert isinstance(missing, dict)
    assert "/tmp/yoke-missing.token" in missing["command"]
    assert "token file is missing" in missing["expected_text"]

    empty = json_helper.load_path(recipe_dir / "AUTH-006.json")
    assert isinstance(empty, dict)
    assert "/tmp/yoke-empty.token" in empty["command"]
    assert "token file is empty" in empty["expected_text"]

    invalid = json_helper.load_path(recipe_dir / "AUTH-007.json")
    assert isinstance(invalid, dict)
    assert "/tmp/yoke-invalid.token" in invalid["command"]
    assert "HTTP 401" in invalid["expected_text"]

    no_access = json_helper.load_path(recipe_dir / "AUTH-008.json")
    assert isinstance(no_access, dict)
    assert "19088" in no_access["command"]
    assert 'rm -f "$HOME/.yoke/config.json"' in no_access["command"]
    assert 'rm -rf "$HOME/.yoke/secrets"' in no_access["command"]
    assert no_access["actions"][3]["keys"] == [
        "http://127.0.0.1:19088",
        "Enter",
    ]
    assert "does not include access" in " ".join(no_access["expected_text"])

    stored = json_helper.load_path(recipe_dir / "AUTH-009.json")
    assert isinstance(stored, dict)
    assert stored["stage_files"] == [
        {"source_path": str(stage_token), "remote_path": str(stage_token)}
    ]
    assert f"cp {stage_token}" in stored["command"]
    assert stored["actions"] == [
        {"step": "000-path-all-clear"},
        {"step": "010-stored-token-result", "keys": ["Enter"]},
    ]
    assert "Using existing Yoke token file" in " ".join(stored["expected_text"])

    stored_invalid = json_helper.load_path(recipe_dir / "AUTH-010.json")
    assert isinstance(stored_invalid, dict)
    assert ".yoke/secrets/stage.token" in stored_invalid["command"]
    assert "not-a-real-yoke-token" in stored_invalid["command"]
    assert "trap restore_stored_token EXIT HUP INT TERM" in stored_invalid["command"]
    assert "HTTP 401" in stored_invalid["expected_text"]

    many = json_helper.load_path(recipe_dir / "AUTH-011.json")
    assert isinstance(many, dict)
    assert "19089" in many["command"]
    assert many["actions"][3]["keys"] == [
        "http://127.0.0.1:19089",
        "Enter",
    ]
    assert "and 2 more" in many["expected_text"]
    assert "no_text:including" in many["post_checks"]


def test_seed_known_recipes_adds_project_source_front_half_recipes(
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
        "PROJECT-SOURCE-001": "prepared-git",
        "PROJECT-SOURCE-002": "prepared-git",
        "PROJECT-SOURCE-003": "prepared-git",
        "PROJECT-SOURCE-004": "prepared-git",
        "PROJECT-SOURCE-005": "prepared-git",
        "PROJECT-SOURCE-006": "prepared-git",
        "PROJECT-SOURCE-007": "prepared-git",
        "PROJECT-SOURCE-008": "prepared-git",
        "PROJECT-SOURCE-009": "prepared-git",
        "PROJECT-SOURCE-010": "prepared-no-git",
        "PROJECT-SOURCE-011": "prepared-no-git",
        "PROJECT-SOURCE-012": "prepared-no-git-no-sudo",
        "PROJECT-SOURCE-013": "prepared-git",
        "PROJECT-SOURCE-014": "prepared-git",
        "PROJECT-SOURCE-015": "prepared-git",
        "PROJECT-SOURCE-016": "prepared-git",
        "PROJECT-SOURCE-017": "prepared-git",
        "PROJECT-SOURCE-018": "prepared-git",
        "PROJECT-SOURCE-019": "prepared-git",
    }
    for scenario_id, profile in profiles.items():
        json_helper.dump_path(
            recipe_dir / f"{scenario_id}.json",
            {
                "scenario_id": scenario_id,
                "status": "blocked",
                "blocked_reason": "exact key/action recipe is not authored",
                "host_profile": profile,
                "actions": [],
                "expected_text": [],
            },
        )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["seeded_count"] == 18
    assert result["unseeded_count"] == 1
    assert result["unseeded"][0]["scenario_id"] == "PROJECT-SOURCE-006"
    assert "HTTPS device-flow and installation fixture" in result["unseeded"][0][
        "reason"
    ]
    for scenario_id in profiles:
        recipe = json_helper.load_path(recipe_dir / f"{scenario_id}.json")
        assert isinstance(recipe, dict)
        expected_status = "blocked" if scenario_id == "PROJECT-SOURCE-006" else "ready"
        assert recipe["status"] == expected_status
        if scenario_id <= "PROJECT-SOURCE-012" and scenario_id != "PROJECT-SOURCE-006":
            assert recipe["stage_files"] == [
                {"source_path": str(stage_token), "remote_path": str(stage_token)}
            ]

    machine_only = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-001.json")
    assert isinstance(machine_only, dict)
    assert "path fix --yes" in machine_only["command"]
    assert machine_only["actions"][-1]["keys"] == [
        "Down",
        "Down",
        "Down",
        "Down",
        "Enter",
    ]
    assert 'Make "stage" your active environment' in machine_only["expected_text"]
    assert "Skip connecting GitHub for now" in machine_only["expected_text"]

    create_folder = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-002.json")
    assert isinstance(create_folder, dict)
    assert "yoke-project-source-new" in create_folder["expected_text"]
    assert create_folder["actions"][-1]["keys"] == [
        "/tmp/yoke-project-source-new",
        "Enter",
    ]

    existing = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-003.json")
    assert isinstance(existing, dict)
    assert "git -C /tmp/yoke-project-source-existing init" in existing["command"]
    assert "yoke-project-source-existing" in existing["expected_text"]
    assert existing["actions"][-1]["keys"] == [
        "/tmp/yoke-project-source-existing",
        "Enter",
    ]

    redirect = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-004.json")
    assert isinstance(redirect, dict)
    assert "That folder already exists." in redirect["expected_text"]
    assert "/tmp/yoke-project-source-existing" in redirect["expected_text"]
    assert "instead of creating a new one" in redirect["expected_text"]

    clone_main = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-005.json")
    assert isinstance(clone_main, dict)
    assert "main-source" in clone_main["command"]
    assert "git clone --bare" in clone_main["command"]
    assert "file:///tmp/yoke-project-source-remotes" not in " ".join(
        clone_main["expected_text"]
    )
    assert clone_main["actions"][-1]["keys"] == [
        "/tmp/yoke-project-source-clone-main",
        "Enter",
    ]

    private_clone = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-006.json")
    assert isinstance(private_clone, dict)
    assert private_clone["status"] == "blocked"
    assert private_clone["blocked_reason"] == "exact key/action recipe is not authored"

    unreachable = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-007.json")
    assert isinstance(unreachable, dict)
    assert "missing-source.git" in unreachable["actions"][-1]["keys"][0]
    assert "Couldn't reach that repo." in unreachable["expected_text"]

    clone_master = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-008.json")
    assert isinstance(clone_master, dict)
    assert "master-source" in clone_master["command"]
    assert (
        "How do you want to copy recipe/master-source?" in clone_master["expected_text"]
    )

    conflict = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-009.json")
    assert isinstance(conflict, dict)
    assert "occupied" in conflict["command"]
    assert conflict["actions"][-1]["keys"] == [
        "/tmp/yoke-project-source-conflict",
        "Enter",
    ]
    assert "That folder already has files" in conflict["expected_text"]

    missing_git = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-010.json")
    assert isinstance(missing_git, dict)
    assert missing_git["actions"][-1] == {
        "step": "070-git-required",
        "keys": ["Enter"],
    }
    assert "Git is required for project setup." in missing_git["expected_text"]

    install_git = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-011.json")
    assert isinstance(install_git, dict)
    assert install_git["actions"][-1] == {
        "step": "080-git-install-returned",
        "keys": ["Enter"],
    }
    assert install_git["step_delay"] == 30.0
    assert "Point at your project folder." in install_git["expected_text"]

    manual_git = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-012.json")
    assert isinstance(manual_git, dict)
    assert "Run this manually" in " ".join(manual_git["expected_text"])

    source_denied = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-013.json")
    assert isinstance(source_denied, dict)
    assert "19107" in source_denied["command"]
    assert source_denied["actions"][-2:] == [
        {"step": "040-source-dev-option", "keys": ["Down", "Down", "Down"]},
        {"step": "041-source-dev-mode", "keys": ["Enter"]},
    ]
    assert "can't reach the Yoke project" in " ".join(source_denied["expected_text"])

    source_allowed = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-014.json")
    assert isinstance(source_allowed, dict)
    assert source_allowed["actions"][-1] == {
        "step": "050-yoke-checkout-input",
        "keys": ["/tmp/yoke-project-source-dev-fresh", "Enter"],
    }
    assert "19106" in source_allowed["command"]
    assert "19108" not in source_allowed["command"]
    assert "Checking Yoke access." not in source_allowed["expected_text"]
    assert "Set up the Yoke source checkout" not in source_allowed["expected_text"]
    assert (
        'Use Yoke\'s GitHub "origin" remote from the clone'
        in (source_allowed["expected_text"])
    )

    source_fresh = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-015.json")
    assert isinstance(source_fresh, dict)
    assert source_fresh["execution_mode"] == "ssh-command"
    assert source_fresh["actions"] == [{"step": "000-source-dev-post-apply"}]
    assert "19112" in source_fresh["command"]
    assert "19113" not in source_fresh["command"]
    assert "source-dev-admin" in source_fresh["command"]
    assert "https://github.com/upyoke/yoke.git" in source_fresh["command"]
    assert "source-dev post-apply proof: ok" in source_fresh["expected_text"]
    assert "post-apply clone/source-link filesystem proof" in source_fresh["notes"]

    source_existing = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-016.json")
    assert isinstance(source_existing, dict)
    assert "19114" in source_existing["command"]
    assert "19115" not in source_existing["command"]
    assert "/tmp/yoke-project-source-dev-existing" in source_existing["command"]
    assert "Set up the Yoke source checkout at" in source_existing["expected_text"]
    assert "Register this checkout in ~/.yoke/config.json" not in source_existing[
        "expected_text"
    ]
    assert source_existing["actions"][-1]["keys"] == [
        "/tmp/yoke-project-source-dev-existing",
        "Enter",
    ]

    source_conflict = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-017.json")
    assert isinstance(source_conflict, dict)
    assert "19116" in source_conflict["command"]
    assert "19117" not in source_conflict["command"]
    assert "/tmp/yoke-project-source-dev-conflict" in source_conflict["command"]
    assert "existing Yoke clone" in " ".join(source_conflict["expected_text"])

    source_default = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-018.json")
    assert isinstance(source_default, dict)
    assert "19118" in source_default["command"]
    assert "19119" not in source_default["command"]
    assert "~/code/yoke" in source_default["expected_text"]
    assert "/tmp/yoke-project-source-dev-default" in source_default["expected_text"]
    assert "Set up the Yoke source checkout" not in source_default["expected_text"]
    assert "Register this checkout in ~/.yoke/config.json" not in source_default[
        "expected_text"
    ]

    source_push = json_helper.load_path(recipe_dir / "PROJECT-SOURCE-019.json")
    assert isinstance(source_push, dict)
    assert "19120" in source_push["command"]
    assert "19121" not in source_push["command"]
    assert "source-dev push review" in source_push["notes"]
    assert "Set up the Yoke source checkout" in source_push["expected_text"]
    assert "Register this checkout in ~/.yoke/config.json" not in source_push[
        "expected_text"
    ]


def test_seed_known_recipes_adds_project_metadata_recipes(
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
        "PROJECT-META-001": "prepared-git",
        "PROJECT-META-002": "prepared-git",
        "PROJECT-META-003": "prepared-git",
        "PROJECT-META-004": "prepared-git",
        "PROJECT-META-005": "prepared-git",
        "PROJECT-META-006": "prepared-git",
        "PROJECT-META-007": "prepared-git",
        "PROJECT-META-008": "prepared-git",
        "PROJECT-META-009": "fault-injection",
        "PROJECT-META-010": "prepared-git",
        "PROJECT-META-011": "prepared-git",
    }
    for scenario_id, profile in profiles.items():
        json_helper.dump_path(
            recipe_dir / f"{scenario_id}.json",
            {
                "scenario_id": scenario_id,
                "status": "blocked",
                "blocked_reason": "exact key/action recipe is not authored",
                "host_profile": profile,
                "actions": [],
                "expected_text": [],
            },
        )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["seeded_count"] == 10
    assert result["unseeded_count"] == 1
    assert result["unseeded"][0]["scenario_id"] == "PROJECT-META-008"
    for scenario_id in profiles:
        recipe = json_helper.load_path(recipe_dir / f"{scenario_id}.json")
        assert isinstance(recipe, dict)
        assert recipe["status"] == (
            "blocked" if scenario_id == "PROJECT-META-008" else "ready"
        )

    valid = json_helper.load_path(recipe_dir / "PROJECT-META-001.json")
    assert isinstance(valid, dict)
    assert valid["stage_files"] == [
        {"source_path": str(stage_token), "remote_path": str(stage_token)}
    ]
    assert "Review what Yoke will save." in valid["expected_text"]
    assert valid["actions"][-3:] == [
        {"step": "190-board-art-save", "keys": ["Enter"]},
        {"step": "200-board-art-continue-option", "keys": ["Down"]},
        {"step": "210-review-from-board-art", "keys": ["Enter"]},
    ]
    assert "Register this checkout in ~/.yoke/config.json" in valid["expected_text"]
    assert "In the Yoke core database" in valid["expected_text"]

    empty_slug = json_helper.load_path(recipe_dir / "PROJECT-META-002.json")
    assert isinstance(empty_slug, dict)
    assert empty_slug["actions"][-1]["keys"] == ["C-u", "Enter"]
    assert "A value is required." in empty_slug["expected_text"]

    invalid_slug = json_helper.load_path(recipe_dir / "PROJECT-META-003.json")
    assert isinstance(invalid_slug, dict)
    assert invalid_slug["actions"][-2] == {
        "step": "090-clear-slug",
        "keys": ["C-u"],
        "capture": False,
    }
    assert invalid_slug["actions"][-1]["keys"] == ["Bad Slug", "Enter"]

    long_slug = json_helper.load_path(recipe_dir / "PROJECT-META-004.json")
    assert isinstance(long_slug, dict)
    assert "a" * 70 in long_slug["actions"][-1]["keys"]
    assert "Use 63 characters or fewer." in long_slug["expected_text"]

    empty_name = json_helper.load_path(recipe_dir / "PROJECT-META-005.json")
    assert isinstance(empty_name, dict)
    assert empty_name["actions"][-1]["keys"] == ["C-u", "Enter"]
    assert "A value is required." in empty_name["expected_text"]

    invalid_branch = json_helper.load_path(recipe_dir / "PROJECT-META-006.json")
    assert isinstance(invalid_branch, dict)
    assert "bad branch" in invalid_branch["actions"][-1]["keys"]
    assert "A branch name can't contain spaces." in invalid_branch["expected_text"]

    invalid_prefix = json_helper.load_path(recipe_dir / "PROJECT-META-007.json")
    assert isinstance(invalid_prefix, dict)
    assert [
        action["step"]
        for action in invalid_prefix["actions"]
        if action["step"] == "120-default-branch-input"
    ] == ["120-default-branch-input"]
    assert invalid_prefix["actions"][-2] == {
        "step": "130-prefix-input-ready",
        "keys": ["Enter"],
    }
    assert invalid_prefix["actions"][-1] == {
        "step": "140-invalid-prefix-error",
        "keys": ["toolong", "Enter"],
    }
    assert (
        "Use 2-6 letters or digits starting with a letter"
        in (invalid_prefix["expected_text"])
    )
    assert "item-prefix inline validation" in invalid_prefix["notes"]

    owner_picker = json_helper.load_path(recipe_dir / "PROJECT-META-008.json")
    assert isinstance(owner_picker, dict)
    assert owner_picker["status"] == "blocked"
    assert owner_picker["blocked_reason"] == "exact key/action recipe is not authored"

    board_fail = json_helper.load_path(recipe_dir / "PROJECT-META-009.json")
    assert isinstance(board_fail, dict)
    assert "19109" in board_fail["command"]
    assert "config.json" in board_fail["command"]
    assert "active_env" in board_fail["command"]
    assert "board.data.get" in board_fail["command"]
    assert "board-art write" in board_fail["notes"]
    assert "board.data.get failed" in board_fail["expected_text"]
    assert "Failed step: 06-project-write-board-art" in board_fail["expected_text"]
    assert board_fail["actions"][0:5] == [
        {"step": "000-path-all-clear"},
        {"step": "010-yoke-stored-token-result", "keys": ["Enter"]},
        {"step": "020-github-picker", "keys": ["Enter"]},
        {"step": "030-github-skip-option", "keys": ["Down"]},
        {"step": "031-project-mode", "keys": ["Enter"]},
    ]
    assert board_fail["actions"][-4:] == [
        {"step": "160-board-art-save", "keys": ["Enter"]},
        {"step": "170-board-art-continue-option", "keys": ["Down"]},
        {"step": "180-review-from-board-art", "keys": ["Enter"]},
        {"step": "190-apply-failure", "keys": ["Enter"]},
    ]

    immediate_tilde = json_helper.load_path(recipe_dir / "PROJECT-META-010.json")
    assert isinstance(immediate_tilde, dict)
    assert (
        "~/code/yoke-project-meta-immediate" in immediate_tilde["actions"][-1]["keys"]
    )
    assert "yoke-project-meta-immediate" in immediate_tilde["expected_text"]

    settled_tilde = json_helper.load_path(recipe_dir / "PROJECT-META-011.json")
    assert isinstance(settled_tilde, dict)
    assert settled_tilde["actions"][-2] == {"step": "090-create-folder-input-ready"}
    assert "~/code/yoke-project-meta-settled" in settled_tilde["actions"][-1]["keys"]
    assert "yoke-project-meta-settled" in settled_tilde["expected_text"]


def test_seed_known_recipes_keeps_github_publish_recipes_manual(
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
        "PUBLISH-001": "prepared-git",
        **{f"PUBLISH-{number:03d}": "prepared-git" for number in range(2, 13)},
    }
    profiles["PUBLISH-008"] = "fault-injection"
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
    assert result["unseeded_count"] == 11
    assert [item["scenario_id"] for item in result["seeded"]] == ["PUBLISH-001"]
    assert {item["scenario_id"] for item in result["unseeded"]} == {
        f"PUBLISH-{number:03d}" for number in range(2, 13)
    }
    assert all(
        "HTTPS device-flow and installation fixture" in item["reason"]
        for item in result["unseeded"]
    )

    local = json_helper.load_path(recipe_dir / "PUBLISH-001.json")
    assert isinstance(local, dict)
    assert local["status"] == "ready"
    assert "No — keep it local" in local["expected_text"]
    assert {"step": "110-publish-prompt", "keys": ["Enter"]} in local["actions"]
    assert {"step": "120-publish-decline-option", "keys": ["Down"]} in local["actions"]
    assert local["stage_files"] == [
        {"source_path": str(stage_token), "remote_path": str(stage_token)}
    ]

    for scenario_id in sorted(set(profiles) - {"PUBLISH-001"}):
        recipe = json_helper.load_path(recipe_dir / f"{scenario_id}.json")
        assert recipe["status"] == "blocked"
        assert recipe["blocked_reason"] == "manual App fixture is required"


def test_seed_known_recipes_adds_apply_recipes(
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
        "APPLY-001": "prepared-yoke",
        "APPLY-002": "prepared-git",
        "APPLY-003": "prepared-git",
        "APPLY-004": "fault-injection",
        "APPLY-005": "fault-injection",
        "APPLY-006": "fault-injection",
        "APPLY-007": "fault-injection",
        "APPLY-008": "fault-injection",
        "APPLY-009": "fault-injection",
        "APPLY-010": "prepared-git",
        "APPLY-011": "prepared-git",
        "APPLY-012": "prepared-git",
    }
    for scenario_id, profile in profiles.items():
        json_helper.dump_path(
            recipe_dir / f"{scenario_id}.json",
            {
                "scenario_id": scenario_id,
                "status": "blocked",
                "blocked_reason": "exact key/action recipe is not authored",
                "host_profile": profile,
                "actions": [],
                "expected_text": [],
            },
        )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["seeded_count"] == 10
    assert result["unseeded_count"] == 2
    assert {item["scenario_id"] for item in result["unseeded"]} == {
        "APPLY-005",
        "APPLY-008",
    }
    for scenario_id in profiles:
        recipe = json_helper.load_path(recipe_dir / f"{scenario_id}.json")
        assert isinstance(recipe, dict)
        if scenario_id in {"APPLY-005", "APPLY-008"}:
            assert recipe["status"] == "blocked"
        else:
            assert recipe["status"] == "ready"
            assert not any(
                "board-art-gallery" in str(action.get("step", ""))
                for action in recipe["actions"]
            )

    machine = json_helper.load_path(recipe_dir / "APPLY-001.json")
    assert isinstance(machine, dict)
    assert "onboard --non-interactive --quick" in machine["command"]
    assert machine["execution_mode"] == "ssh-command"
    assert machine["stage_files"] == [
        {"source_path": str(stage_token), "remote_path": str(stage_token)}
    ]
    assert '"final_status": "done"' in machine["expected_text"]

    create_review = json_helper.load_path(recipe_dir / "APPLY-002.json")
    assert isinstance(create_review, dict)
    assert "yoke-apply-create" in create_review["expected_text"]
    assert "Yoke core database" in create_review["expected_text"]
    assert "GitHub" in create_review["expected_text"]
    assert "Apply" in create_review["expected_text"]
    assert "Review what Yoke will save." not in create_review["expected_text"]
    assert "Nothing is written until you choose Apply." not in create_review["expected_text"]
    assert "On this machine (~/.yoke)" not in create_review["expected_text"]
    assert "In your project folder" not in create_review["expected_text"]
    assert (
        "Write your board art and initial BOARD.md"
        not in create_review["expected_text"]
    )

    clone_review = json_helper.load_path(recipe_dir / "APPLY-003.json")
    assert isinstance(clone_review, dict)
    assert "clone-remote" in clone_review["command"]
    assert clone_review["execution_mode"] == "ssh-command"
    assert "git clone --bare" in clone_review["command"]
    assert '"project-clone-remote"' in clone_review["expected_text"]

    machine_fail = json_helper.load_path(recipe_dir / "APPLY-004.json")
    assert isinstance(machine_fail, dict)
    assert machine_fail["expected_return_codes"] == [1]
    assert "/dev/null/config.json" in machine_fail["command"]
    assert "resume:" in machine_fail["expected_text"]
    assert "03-store-token-reference" in machine_fail["expected_text"]
    assert "File exists: '/dev/null'" in machine_fail["expected_text"]

    binding_fail = json_helper.load_path(recipe_dir / "APPLY-005.json")
    assert isinstance(binding_fail, dict)
    assert binding_fail["status"] == "blocked"

    create_fail = json_helper.load_path(recipe_dir / "APPLY-006.json")
    assert isinstance(create_fail, dict)
    assert "projects.get" in create_fail["command"]
    assert "not_found" in create_fail["command"]
    assert "19119" in create_fail["command"]
    assert "project.create" in create_fail["expected_text"][0]

    clone_fail = json_helper.load_path(recipe_dir / "APPLY-007.json")
    assert isinstance(clone_fail, dict)
    assert "/tmp/yoke-apply-clone-conflict" in clone_fail["command"]
    assert "pick an empty folder to resume cleanly" in clone_fail["expected_text"]

    publish_fail = json_helper.load_path(recipe_dir / "APPLY-008.json")
    assert isinstance(publish_fail, dict)
    assert publish_fail["status"] == "blocked"

    board_fail = json_helper.load_path(recipe_dir / "APPLY-009.json")
    assert isinstance(board_fail, dict)
    assert "19121" in board_fail["command"]
    assert "--no-onboard" in board_fail["command"]
    assert board_fail["start_delay"] == 45.0
    assert "config.json" in board_fail["command"]
    assert "payload.pop('\"'\"'github'\"'\"',None)" in board_fail["command"]
    assert board_fail["actions"][-4:] == [
        {"step": "190-board-art-save", "keys": ["Enter"]},
        {"step": "200-board-art-continue-option", "keys": ["Down"]},
        {"step": "210-review-from-board-art", "keys": ["Enter"]},
        {"step": "220-apply", "keys": ["Enter"]},
    ]
    assert "Applying your setup." not in board_fail["expected_text"]
    assert "Couldn't finish setup." not in board_fail["expected_text"]
    assert "couldn't write your board art" in board_fail["expected_text"]
    assert "project-write-board-art" in board_fail["expected_text"]

    resume = json_helper.load_path(recipe_dir / "APPLY-010.json")
    assert isinstance(resume, dict)
    assert "run-apply-resume" in resume["command"]
    assert "onboarding-runs" in resume["command"]
    assert "home/'runs'/'apply-reports'" not in resume["command"]
    assert resume["execution_mode"] == "ssh-command"
    assert (
        '"resume_command": "yoke onboard --resume run-apply-resume"'
        in resume["expected_text"]
    )

    audit = json_helper.load_path(recipe_dir / "APPLY-011.json")
    assert isinstance(audit, dict)
    assert "19120" in audit["command"]
    assert audit["execution_mode"] == "ssh-command"
    assert "onboarding-runs/apply-reports" in audit["expected_text"]

    ctrl_c = json_helper.load_path(recipe_dir / "APPLY-012.json")
    assert isinstance(ctrl_c, dict)
    assert "19123" in ctrl_c["command"]
    assert "--no-onboard" in ctrl_c["command"]
    assert "board.data.get" in ctrl_c["command"]
    assert "board_data" in ctrl_c["command"]
    assert "board_data_by_scope" in ctrl_c["command"]
    assert "onboard.checklist.run" in ctrl_c["command"]
    assert '"91"' in ctrl_c["command"]
    assert "Applying your setup." in ctrl_c["expected_text"]
    assert "Saved .yoke/board-art and rebuilt your board." in ctrl_c[
        "expected_text"
    ]
    assert "Finish" not in ctrl_c["expected_text"]
    assert "no_text:Couldn't finish setup." in ctrl_c["post_checks"]
    assert ctrl_c["start_delay"] == 45.0
    assert ctrl_c["actions"][-1] == {
        "step": "210-ctrl-c-during-apply",
        "keys": ["C-c"],
    }


def test_apply_fake_board_data_payload_replays() -> None:
    from yoke_contracts.board.art import ArtConfig
    from yoke_contracts.board.config import parse_config
    from yoke_contracts.board.renderer import render_board_from_payload

    repo_root = "/tmp/yoke-apply-ctrl-c"
    config = parse_config(None, repo_root=repo_root)

    payload = coordinator._payload_with_board_data(
        coordinator._fake_apply_yoke_payload(),
        path=repo_root,
    )
    board_data_by_scope = payload["board_data_by_scope"]
    assert isinstance(board_data_by_scope, dict)
    assert set(board_data_by_scope) == {"all", "yoke", "91"}

    for scope, scope_payload in board_data_by_scope.items():
        rendered = render_board_from_payload(
            scope_payload,
            scope=scope,
            config=config,
            art_config=ArtConfig(),
            repo_root=repo_root,
            vision_entries=[],
        )
        assert scope_payload["entry_count"] > 0
        assert "THE BOARD" in rendered

    assert payload["board_data"] == board_data_by_scope["91"]


def test_seed_known_recipes_adds_terminal_and_state_recipes(
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
        **{f"TERM-{index:03d}": "prepared-git" for index in range(1, 4)},
        "TERM-004": "prepared-screen-term",
        "TERM-005": "prepared-screen-term",
        **{f"TERM-{index:03d}": "prepared-git" for index in range(6, 13)},
        **{f"STATE-{index:03d}": "prepared-stored-state" for index in range(1, 10)},
    }
    for scenario_id, profile in profiles.items():
        json_helper.dump_path(
            recipe_dir / f"{scenario_id}.json",
            {
                "scenario_id": scenario_id,
                "status": "blocked",
                "blocked_reason": "exact key/action recipe is not authored",
                "host_profile": profile,
                "actions": [],
                "expected_text": [],
            },
        )

    result = coordinator.seed_known_recipes(campaign_root=campaign_root)

    assert result["seeded_count"] == 19
    assert result["unseeded_count"] == 2
    assert {item["scenario_id"] for item in result["unseeded"]} == {
        "STATE-002",
        "STATE-007",
    }
    for scenario_id in profiles:
        recipe = json_helper.load_path(recipe_dir / f"{scenario_id}.json")
        assert isinstance(recipe, dict)
        assert recipe["status"] == (
            "blocked" if scenario_id in {"STATE-002", "STATE-007"} else "ready"
        )

    term_size = json_helper.load_path(recipe_dir / "TERM-003.json")
    assert isinstance(term_size, dict)
    assert "tmux resize-window -x 140 -y 40" in term_size["command"]
    assert set(coordinator.PATH_HEALTH_EXPECTED_TEXT).issubset(
        term_size["expected_text"]
    )
    assert "Where should this Yoke live?" in term_size["expected_text"]
    assert "Yoke is already on your PATH." not in term_size["expected_text"]

    single_action = json_helper.load_path(recipe_dir / "TERM-006.json")
    assert isinstance(single_action, dict)
    assert single_action["actions"] == [
        {"step": "000-path-all-clear"},
        {"step": "010-up-stays-on-continue", "keys": ["Up"]},
        {"step": "020-down-stays-on-continue", "keys": ["Down"]},
    ]
    assert set(coordinator.PATH_HEALTH_EXPECTED_TEXT).issubset(
        single_action["expected_text"]
    )
    assert "Continue" in single_action["expected_text"]
    assert "Quit" not in single_action["expected_text"]
    assert "no_text:Quit" in single_action["post_checks"]

    space_select = json_helper.load_path(recipe_dir / "TERM-007.json")
    assert isinstance(space_select, dict)
    assert list(coordinator.PATH_HEALTH_CONNECT_EXPECTED_TEXT) == space_select[
        "expected_text"
    ]

    escape_back = json_helper.load_path(recipe_dir / "TERM-009.json")
    assert isinstance(escape_back, dict)
    assert set(coordinator.PATH_HEALTH_EXPECTED_TEXT).issubset(
        escape_back["expected_text"]
    )
    assert "Where should this Yoke live?" in escape_back["expected_text"]

    plain = json_helper.load_path(recipe_dir / "TERM-004.json")
    assert isinstance(plain, dict)
    assert "YOKE_ONBOARD_FORCE_PLAIN=1" in plain["command"]
    assert "Add Yoke to your PATH." in plain["expected_text"]
    assert set(coordinator.PATH_HEALTH_PLAIN_EXPECTED_TEXT).issubset(
        plain["expected_text"]
    )
    assert ">  Add yoke to my PATH" not in plain["expected_text"]
    assert "no_text:☀" in plain["post_checks"]

    dumb = json_helper.load_path(recipe_dir / "TERM-005.json")
    assert isinstance(dumb, dict)
    assert "TERM=dumb" in dumb["command"]
    assert "Add Yoke to your PATH." in dumb["expected_text"]
    assert set(coordinator.PATH_HEALTH_PLAIN_EXPECTED_TEXT).issubset(
        dumb["expected_text"]
    )
    assert ">  Add yoke to my PATH" not in dumb["expected_text"]

    ctrl_c = json_helper.load_path(recipe_dir / "TERM-010.json")
    assert isinstance(ctrl_c, dict)
    assert ctrl_c["actions"][-1] == {
        "step": "010-ctrl-c",
        "keys": ["C-c"],
        "capture": False,
    }
    assert list(coordinator.PATH_HEALTH_EXPECTED_TEXT) == ctrl_c["expected_text"]
    assert "tmux_exit_code:130" in ctrl_c["post_checks"]

    screen_compat = json_helper.load_path(recipe_dir / "TERM-011.json")
    assert isinstance(screen_compat, dict)
    assert set(coordinator.PATH_HEALTH_PLAIN_EXPECTED_TEXT).issubset(
        screen_compat["expected_text"]
    )
    assert "your shell is ready" not in screen_compat["expected_text"]
    assert "Yoke is already on your PATH." not in screen_compat["expected_text"]

    long_name = json_helper.load_path(recipe_dir / "TERM-012.json")
    assert isinstance(long_name, dict)
    assert long_name["stage_files"] == [
        {"source_path": str(stage_token), "remote_path": str(stage_token)}
    ]
    assert long_name["actions"][-2] == {
        "step": "090-project-name-input",
        "keys": ["Enter"],
    }
    assert long_name["actions"][-1] == {
        "step": "100-publish-prompt",
        "keys": ["Enter"],
    }
    assert coordinator.TERM_LONG_PROJECT_NAME in long_name["expected_text"]

    account = json_helper.load_path(recipe_dir / "STATE-001.json")
    assert isinstance(account, dict)
    assert "/install" in account["command"]
    assert "state-001-install-refresh.log" in account["command"]
    assert "yoke-state-restore-env.json" in account["command"]
    assert "Using existing environment:" in account["expected_text"]
    assert account["start_delay"] == coordinator.STATE_TUI_SETUP_START_DELAY

    github = json_helper.load_path(recipe_dir / "STATE-002.json")
    assert isinstance(github, dict)
    assert github["status"] == "blocked"

    one_project = json_helper.load_path(recipe_dir / "STATE-003.json")
    assert isinstance(one_project, dict)
    assert "19124" in one_project["command"]
    assert "state-project-19124-install-refresh.log" in one_project["command"]
    assert "project register /tmp/yoke-state-project-one" in one_project["command"]
    assert "yoke-state-project-register-101.json" in one_project["command"]
    assert one_project["actions"][:4] == [
        {"step": "000-path-all-clear"},
        {"step": "010-yoke-stored-token-result", "keys": ["Enter"]},
        {"step": "020-github-prompt", "keys": ["Enter"]},
        {"step": "030-github-skip", "keys": ["Down", "Enter"]},
    ]
    assert one_project["actions"][4] == {"step": "040-existing-project-ready"}
    assert "Existing Yoke project found." in one_project["expected_text"]

    multiple_projects = json_helper.load_path(recipe_dir / "STATE-004.json")
    assert isinstance(multiple_projects, dict)
    assert "state-project-19125-install-refresh.log" in multiple_projects["command"]
    assert "yoke-state-project-register-102.json" in multiple_projects["command"]
    assert "Use an existing checkout?" in multiple_projects["expected_text"]
    assert coordinator.STATE_PROJECT_TWO_PATH in multiple_projects["expected_text"]

    missing_project = json_helper.load_path(recipe_dir / "STATE-005.json")
    assert isinstance(missing_project, dict)
    assert "state-project-19126-install-refresh.log" in missing_project["command"]
    assert "project 404 was not found" in missing_project["command"]
    assert "Can't use that Yoke project." in missing_project["expected_text"]

    env_switch = json_helper.load_path(recipe_dir / "STATE-006.json")
    assert isinstance(env_switch, dict)
    assert env_switch["execution_mode"] == "ssh-command"
    assert "state-env-switch-install-refresh.log" in env_switch["command"]
    assert "YOKE_ENV=prod" in env_switch["command"]
    assert '"active_env": "stage"' not in env_switch["expected_text"]
    assert (
        f'"api_url": "{coordinator.HOSTED_STAGE_API_URL}"'
        in env_switch["expected_text"]
    )
    assert (
        f'"api_url": "{coordinator.HOSTED_PROD_API_URL}"'
        in env_switch["expected_text"]
    )

    repeat = json_helper.load_path(recipe_dir / "STATE-007.json")
    assert isinstance(repeat, dict)
    assert repeat["status"] == "blocked"

    one_shot = json_helper.load_path(recipe_dir / "STATE-008.json")
    assert isinstance(one_shot, dict)
    assert "state-one-shot-path-install-refresh.log" in one_shot["command"]
    assert "command -v yoke; yoke --version" in one_shot["command"]

    reinstall = json_helper.load_path(recipe_dir / "STATE-009.json")
    assert isinstance(reinstall, dict)
    assert "/install -o /tmp/yoke-state-install" in reinstall["command"]


def test_compile_recipes_writes_specs_and_blocks_unready_recipes(
    tmp_path: Path,
) -> None:
    campaign_root = tmp_path / "campaign"
    _write_assignment(
        campaign_root,
        "A001",
        "bare-no-uv",
        ["INSTALL-SMOKE-001", "INSTALL-SMOKE-002"],
    )
    ledger_path = _write_ledger(tmp_path, profile="bare-no-uv")
    coordinator.assign_hosts(campaign_root=campaign_root, ledger_path=ledger_path)
    spec_dir = campaign_root / "run-specs"
    spec_dir.mkdir()
    (spec_dir / "run-spec-999.json").write_text("{}", encoding="utf-8")
    recipe_dir = campaign_root / "recipe-stubs"
    recipe_dir.mkdir(parents=True)
    json_helper.dump_path(
        recipe_dir / "INSTALL-SMOKE-001.json",
        {
            "scenario_id": "INSTALL-SMOKE-001",
            "status": "ready",
            "command": "TERM=xterm-256color yoke onboard",
            "actions": [{"step": "000-initial"}],
            "expected_text": ["Set up your machine"],
            "post_checks": ["secret_free"],
        },
    )
    json_helper.dump_path(
        recipe_dir / "INSTALL-SMOKE-002.json",
        {
            "scenario_id": "INSTALL-SMOKE-002",
            "status": "blocked",
            "blocked_reason": "needs non-interactive installer assertion recipe",
        },
    )

    result = coordinator.compile_recipes(campaign_root=campaign_root)

    assert result["ok"] is False
    assert result["run_count"] == 1
    assert result["run_spec_count"] == 1
    assert result["blocked_count"] == 1
    assert result["blocked"][0]["scenario_id"] == "INSTALL-SMOKE-002"
    spec = json_helper.load_path(campaign_root / "run-specs" / "run-spec-001.json")
    assert isinstance(spec, dict)
    assert spec["ledger"] == str(ledger_path)
    assert spec["runs"] == [
        {
            "assignment_id": "A001",
            "scenario_id": "INSTALL-SMOKE-001",
            "host_id": "tui-linux-001",
            "command": "TERM=xterm-256color yoke onboard",
            "actions": [{"step": "000-initial", "keys": []}],
            "expected_text": ["Set up your machine"],
            "post_checks": ["secret_free"],
            "stage_files": [],
            "execution_mode": "tmux",
            "expected_return_codes": [0],
            "pane": "ob",
            "start_delay": 3.0,
            "step_delay": 0.5,
            "max_wall_seconds": coordinator.scenario_runner.DEFAULT_MAX_WALL_SECONDS,
            "reset_profile": "bare-no-uv",
        }
    ]
    assert not (campaign_root / "run-specs" / "run-spec-999.json").exists()


def test_compile_recipes_blocks_missing_local_stage_source(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign"
    _write_assignment(
        campaign_root,
        "A001",
        "prepared-yoke",
        ["INSTALL-SMOKE-004"],
    )
    ledger_path = _write_ledger(tmp_path, profile="prepared-yoke")
    coordinator.assign_hosts(campaign_root=campaign_root, ledger_path=ledger_path)
    recipe_dir = campaign_root / "recipe-stubs"
    recipe_dir.mkdir(parents=True)
    missing = tmp_path / "missing-stage-token"
    json_helper.dump_path(
        recipe_dir / "INSTALL-SMOKE-004.json",
        {
            "scenario_id": "INSTALL-SMOKE-004",
            "status": "ready",
            "command": '"$HOME/.local/bin/yoke" onboard --yes',
            "actions": [{"step": "000-machine-only-stage"}],
            "expected_text": ['"applied": true'],
            "stage_files": [
                {
                    "source_path": str(missing),
                    "remote_path": "/tmp/yoke-stage.token",
                }
            ],
        },
    )

    result = coordinator.compile_recipes(campaign_root=campaign_root)

    assert result["ok"] is False
    assert result["run_count"] == 0
    assert result["blocked_count"] == 1
    assert result["blocked"][0]["scenario_id"] == "INSTALL-SMOKE-004"
    assert "stage source_path is not readable" in result["blocked"][0]["reason"]


def test_compile_recipes_resets_prepared_stored_state_runs(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign"
    _write_assignment(
        campaign_root,
        "A039",
        "prepared-stored-state",
        ["STATE-001"],
    )
    ledger_path = _write_ledger(tmp_path, profile="prepared-stored-state")
    coordinator.assign_hosts(campaign_root=campaign_root, ledger_path=ledger_path)
    recipe_dir = campaign_root / "recipe-stubs"
    recipe_dir.mkdir(parents=True)
    json_helper.dump_path(
        recipe_dir / "STATE-001.json",
        {
            "scenario_id": "STATE-001",
            "status": "ready",
            "command": '"$HOME/.local/bin/yoke" onboard',
            "actions": [{"step": "000-stored-state"}],
            "expected_text": ["Using existing environment:"],
            "post_checks": ["secret_free"],
        },
    )

    result = coordinator.compile_recipes(campaign_root=campaign_root)

    assert result["ok"] is True
    spec = json_helper.load_path(campaign_root / "run-specs" / "run-spec-001.json")
    assert spec["runs"][0]["reset_profile"] == "prepared-stored-state"


def test_run_batch_dry_run_does_not_write_summary(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign"
    ledger_path = _write_ledger(tmp_path, profile="bare-no-uv")
    spec_path = _write_run_spec(campaign_root, ledger_path)

    result = coordinator.run_batch(spec_path=spec_path, execute=False)

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["run_count"] == 1
    assert result["runs"][0]["max_wall_seconds"] == (
        coordinator.scenario_runner.DEFAULT_MAX_WALL_SECONDS
    )
    assert not (campaign_root / "summaries").exists()


def test_run_batch_dry_run_accepts_wall_clock_override(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign"
    ledger_path = _write_ledger(tmp_path, profile="bare-no-uv")
    spec_path = _write_run_spec(campaign_root, ledger_path)

    result = coordinator.run_batch(
        spec_path=spec_path,
        execute=False,
        max_wall_seconds=42,
    )

    assert result["ok"] is True
    assert result["runs"][0]["max_wall_seconds"] == 42


def test_run_batch_executes_reset_and_runner_sequence(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign"
    ledger_path = _write_ledger(tmp_path, profile="bare-no-uv")
    spec_path = _write_run_spec(campaign_root, ledger_path)
    fake = FakeRunner(["Set up your machine\nAdd yoke to my PATH\n"])

    result = coordinator.run_batch(
        spec_path=spec_path,
        execute=True,
        runner=fake,
        sleeper=lambda _seconds: None,
    )

    assert result["ok"] is True
    assert result["run_count"] == 1
    assert Path(str(result["summary_path"])).is_file()
    assert result["results"][0]["overall_result"] == "pass"
    report = json_helper.load_path(
        campaign_root / "reports" / "A001-INSTALL-SMOKE-001.json"
    )
    assert report["scenarios"][0]["assertions"]["max_wall_seconds"] == (
        coordinator.scenario_runner.DEFAULT_MAX_WALL_SECONDS
    )
    commands = [call[-1] for call in fake.calls]
    assert any("tmux kill-server" in command for command in commands)
    assert any("tmux new-session" in command for command in commands)
    assert any("capture-pane" in command for command in commands)
    assert (campaign_root / "reports" / "A001-INSTALL-SMOKE-001.json").is_file()


def test_run_waves_dry_run_summarizes_specs(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign"
    ledger_path = _write_ledger(tmp_path, profile="bare-no-uv")
    spec_dir = campaign_root / "run-specs"
    _write_run_spec(campaign_root, ledger_path, spec_dir=spec_dir)
    _write_run_spec(
        campaign_root,
        ledger_path,
        spec_dir=spec_dir,
        name="wave-002.json",
        assignment_id="A002",
        scenario_id="INSTALL-SMOKE-002",
    )

    result = coordinator.run_waves(
        spec_dir=spec_dir,
        execute=False,
        max_parallel=2,
    )

    assert result["ok"] is True
    assert result["dry_run"] is True
    assert result["spec_count"] == 2
    assert result["run_count"] == 2
    assert [batch["run_count"] for batch in result["batches"]] == [1, 1]
    assert not (campaign_root / "summaries").exists()


def test_run_waves_executes_specs_and_writes_aggregate_summary(tmp_path: Path) -> None:
    campaign_root = tmp_path / "campaign"
    ledger_path = _write_ledger(tmp_path, profile="bare-no-uv")
    spec_dir = campaign_root / "run-specs"
    _write_run_spec(campaign_root, ledger_path, spec_dir=spec_dir)
    _write_run_spec(
        campaign_root,
        ledger_path,
        spec_dir=spec_dir,
        name="wave-002.json",
        assignment_id="A002",
        scenario_id="INSTALL-SMOKE-002",
    )

    result = coordinator.run_waves(
        spec_dir=spec_dir,
        execute=True,
        max_parallel=2,
        runner_factory=lambda: FakeRunner(["Set up your machine\n"]),
        sleeper=lambda _seconds: None,
    )

    assert result["ok"] is True
    assert result["spec_count"] == 2
    assert result["run_count"] == 2
    assert Path(str(result["summary_path"])).is_file()
    assert len(result["results"]) == 2
    assert all(item["ok"] is True for item in result["results"])
    assert (campaign_root / "reports" / "A001-INSTALL-SMOKE-001.json").is_file()
    assert (campaign_root / "reports" / "A002-INSTALL-SMOKE-002.json").is_file()
    assert any(
        path.name.startswith("coordinator-waves-")
        for path in (campaign_root / "summaries").glob("*.json")
    )


def test_run_waves_serializes_specs_that_share_a_host(
    tmp_path: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    campaign_root = tmp_path / "campaign"
    ledger_path = _write_ledger(tmp_path, profile="bare-no-uv")
    spec_dir = campaign_root / "run-specs"
    _write_run_spec(campaign_root, ledger_path, spec_dir=spec_dir)
    _write_run_spec(
        campaign_root,
        ledger_path,
        spec_dir=spec_dir,
        name="wave-002.json",
        assignment_id="A002",
        scenario_id="INSTALL-SMOKE-002",
    )
    original_run_batch = coordinator.run_batch
    lock = threading.Lock()
    active = 0
    max_active = 0

    def fake_run_batch(**kwargs):  # noqa: ANN003, ANN202
        nonlocal active, max_active
        if not kwargs["execute"]:
            return original_run_batch(**kwargs)
        with lock:
            active += 1
            max_active = max(max_active, active)
        try:
            time.sleep(0.01)
            return {
                "ok": True,
                "campaign_root": str(campaign_root),
                "ledger_path": str(ledger_path),
                "run_count": 1,
                "results": [],
            }
        finally:
            with lock:
                active -= 1

    monkeypatch.setattr(coordinator, "run_batch", fake_run_batch)

    result = coordinator.run_waves(
        spec_dir=spec_dir,
        execute=True,
        max_parallel=2,
        sleeper=lambda _seconds: None,
    )

    assert result["ok"] is True
    assert max_active == 1


def test_run_waves_writes_aggregate_summary_when_batch_raises(
    tmp_path: Path,
    monkeypatch,  # noqa: ANN001
) -> None:
    campaign_root = tmp_path / "campaign"
    ledger_path = _write_ledger(tmp_path, profile="bare-no-uv")
    spec_dir = campaign_root / "run-specs"
    _write_run_spec(campaign_root, ledger_path, spec_dir=spec_dir)
    original_run_batch = coordinator.run_batch

    def fake_run_batch(**kwargs):  # noqa: ANN003, ANN202
        if kwargs["execute"]:
            raise RuntimeError("runner unavailable")
        return original_run_batch(**kwargs)

    monkeypatch.setattr(coordinator, "run_batch", fake_run_batch)

    result = coordinator.run_waves(
        spec_dir=spec_dir,
        execute=True,
        max_parallel=1,
        sleeper=lambda _seconds: None,
    )

    assert result["ok"] is False
    assert result["run_count"] == 0
    assert result["results"] == [
        {
            "ok": False,
            "spec_path": str(spec_dir / "run-spec.json"),
            "failure": "runner unavailable",
        }
    ]
    assert Path(str(result["summary_path"])).is_file()


def _write_strategy_plan(tmp_path: Path) -> Path:
    path = tmp_path / "INSTALLER-TESTING-PLAN.md"
    path.write_text(
        """
### Wave 1: Installer And First Wizard Smoke

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `INSTALL-SMOKE-001` | `bare-no-uv` | Interactive installer | welcome renders |
| `INSTALL-SMOKE-002` | `bare-no-uv` | Installer `--yes` | no TUI launch |

### Wave 6: Project Source Picker

| ID | Profile | Flow | Assertions |
| --- | --- | --- | --- |
| `PROJECT-SOURCE-005` | `prepared-git` | Clone public repo URL | source reachable |

### Wave 12: macOS Lane (agent-driven visual, single-agent serial)

| ID | Host | Flow | Assertions |
| --- | --- | --- | --- |
| `MAC-001` | test Mac | Stage installer in real SSH TTY | PATH repair works |
""".strip(),
        encoding="utf-8",
    )
    return path


def _write_assignment(
    campaign_root: Path,
    assignment_id: str,
    profile: str,
    scenario_ids: list[str],
) -> None:
    assignments = campaign_root / "assignments"
    assignments.mkdir(parents=True, exist_ok=True)
    json_helper.dump_path(
        assignments / f"{assignment_id}.json",
        {
            "assignment_id": assignment_id,
            "endpoint": "stage",
            "campaign_root": str(campaign_root),
            "host_profile": profile,
            "scenario_ids": scenario_ids,
            "scenarios": [],
            "rules": [],
        },
    )


def _write_ledger(tmp_path: Path, *, profile: str) -> Path:
    key_path = tmp_path / "host.pem"
    key_path.write_text("PRIVATE\n", encoding="utf-8")
    ledger_path = tmp_path / "host-ledger.json"
    json_helper.dump_path(
        ledger_path,
        {
            "key_path": str(key_path),
            "ssh_user": "ubuntu",
            "hosts": [
                {
                    "host_id": "tui-linux-001",
                    "instance_id": "i-123",
                    "public_ip": "203.0.113.10",
                    "profile": profile,
                    "lease_state": "available",
                    "ssh_user": "ubuntu",
                }
            ],
        },
    )
    return ledger_path


def _write_run_spec(
    campaign_root: Path,
    ledger_path: Path,
    *,
    spec_dir: Path | None = None,
    name: str = "run-spec.json",
    assignment_id: str = "A001",
    scenario_id: str = "INSTALL-SMOKE-001",
) -> Path:
    spec_path = (spec_dir or campaign_root) / name
    spec_path.parent.mkdir(parents=True, exist_ok=True)
    json_helper.dump_path(
        spec_path,
        {
            "campaign_root": str(campaign_root),
            "ledger": str(ledger_path),
            "runs": [
                {
                    "assignment_id": assignment_id,
                    "scenario_id": scenario_id,
                    "host_id": "tui-linux-001",
                    "reset_profile": "bare-no-uv",
                    "command": "TERM=xterm-256color yoke onboard",
                    "actions": [{"step": "000-initial"}],
                    "expected_text": ["Set up your machine"],
                    "start_delay": 0,
                    "step_delay": 0,
                }
            ],
        },
    )
    return spec_path
