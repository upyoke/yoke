"""Machine setup installs machine-wide hooks, with or without a project."""

from __future__ import annotations

import json
from pathlib import Path

from yoke_cli.config import harness_posture_install, onboard_project, onboard_report
from yoke_cli.config import onboard_machine_reuse
from yoke_cli.config.onboard_wizard_plan_review import classify_plan
from yoke_contracts.harness_machine_hooks import MACHINE_HOOKS_PLAN_ACTION


def _home(tmp_path):
    return tmp_path / "harness-home"  # the conftest-isolated home


def _plan() -> dict:
    reuse = {
        onboard_machine_reuse.MACHINE_HOOKS: (
            onboard_machine_reuse.current_machine_hook_targets()
        )
    }
    return onboard_report.build_plan(
        Path("/home/.yoke/config.json"),
        "prod",
        "https://api.test",
        {"kind": "token_file", "path": "/home/.yoke/secrets/prod.token"},
        {"kind": "token_file", "path": "/home/.yoke/secrets/prod.token"},
        "quick",
        project_mode=onboard_project.PROJECT_MODE_MACHINE_ONLY,
        project_inputs={},
        machine_github={"choice": "skip"},
        reuse=reuse,
    )


def _hook_targets(plan: dict) -> list[str]:
    return [
        step["target"]
        for step in plan["steps"]
        if step["action"] == MACHINE_HOOKS_PLAN_ACTION
    ]


def _change_count(plan: dict) -> int:
    return sum(len(lines) for lines in classify_plan({"plan": plan}).values())


def test_plan_lists_one_step_per_harness_missing_its_hooks(tmp_path):
    (_home(tmp_path) / ".claude").mkdir(parents=True)
    (_home(tmp_path) / ".codex").mkdir(parents=True)
    assert _hook_targets(_plan()) == [
        "~/.claude/settings.json",
        "~/.codex/hooks.json",
    ]


def test_plan_omits_harnesses_whose_hooks_are_installed(tmp_path):
    (_home(tmp_path) / ".claude").mkdir(parents=True)
    (_home(tmp_path) / ".cursor").mkdir(parents=True)
    before = _plan()
    assert len(_hook_targets(before)) == 2

    harness_posture_install.apply_reported()

    after = _plan()
    assert _hook_targets(after) == []
    assert _change_count(after) == _change_count(before) - 2


def test_plan_still_lists_a_stale_harness(tmp_path):
    (_home(tmp_path) / ".claude").mkdir(parents=True)
    (_home(tmp_path) / ".cursor").mkdir(parents=True)
    harness_posture_install.apply_reported()
    cursor = _home(tmp_path) / ".cursor" / "hooks.json"
    document = json.loads(cursor.read_text())
    for entries in document["hooks"].values():
        for entry in entries:
            entry["command"] = entry["command"] + " --stale"
    cursor.write_text(json.dumps(document))

    assert _hook_targets(_plan()) == ["~/.cursor/hooks.json"]


def test_apply_installs_and_reports_each_harness(tmp_path):
    (_home(tmp_path) / ".claude").mkdir(parents=True)
    (_home(tmp_path) / ".cursor").mkdir(parents=True)
    events = []
    result = harness_posture_install.apply_reported(
        progress=lambda action, target, status: events.append((action, target, status)),
    )

    assert (MACHINE_HOOKS_PLAN_ACTION, "~/.claude/settings.json", "done") in events
    assert (MACHINE_HOOKS_PLAN_ACTION, "~/.cursor/hooks.json", "done") in events
    assert any(
        line.startswith("claude-code: machine_hooks written ")
        for line in result.lines()
    )
    settings = json.loads((_home(tmp_path) / ".claude" / "settings.json").read_text())
    assert "SessionStart" in settings["hooks"]


def test_apply_reports_a_malformed_config_as_failed_with_recovery(tmp_path):
    claude = _home(tmp_path) / ".claude"
    claude.mkdir(parents=True)
    (claude / "settings.json").write_text("{broken")
    events = []
    result = harness_posture_install.apply_reported(
        progress=lambda action, target, status: events.append((action, target, status)),
    )

    assert (MACHINE_HOOKS_PLAN_ACTION, "~/.claude/settings.json", "failed") in events
    line = next(
        line
        for line in result.lines()
        if line.startswith("claude-code: machine_hooks refused ")
    )
    assert "malformed" in line
    assert "yoke doctor run --only harness-setup --fix" in line
    assert (claude / "settings.json").read_text() == "{broken"


def test_no_installed_harness_writes_nothing(tmp_path):
    events = []
    result = harness_posture_install.apply_reported(
        progress=lambda action, target, status: events.append((action, target, status)),
    )
    assert events == [] and all("skipped_no_home" in line for line in result.lines())
    assert not _home(tmp_path).exists()


def test_human_setup_shows_facet_failure_and_recovery():
    from yoke_cli.config.onboard_report_render import render_human

    from yoke_harness.harness_setup_reconcile import HarnessSetupResult, HarnessSetupRow

    result = HarnessSetupResult(
        (
            HarnessSetupRow(
                "config",
                "codex",
                "hook_trust",
                "failed",
                "invalid TOML",
                "repair config; yoke doctor run --only harness-setup --fix",
            ),
        )
    )
    refusal = result.lines()[0]
    report = {
        "mode": "hosted",
        "config_path": "config",
        "applied": True,
        "plan": {"steps": []},
        "identity": {},
        "next_steps": [],
        "harness_setup": result.payload(),
    }
    assert refusal in render_human(report)
