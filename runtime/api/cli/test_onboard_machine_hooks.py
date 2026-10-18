"""Machine setup installs machine-wide hooks, with or without a project."""

from __future__ import annotations

import json

from yoke_cli.config import harness_posture_install
from yoke_contracts.harness_machine_hooks import (
    MACHINE_HOOKS_PLAN_ACTION,
    machine_hooks_plan_steps,
)


def _home(tmp_path):
    return tmp_path / "harness-home"  # the conftest-isolated home


def test_plan_lists_one_step_per_installed_harness(tmp_path):
    (_home(tmp_path) / ".claude").mkdir(parents=True)
    (_home(tmp_path) / ".codex").mkdir(parents=True)
    assert machine_hooks_plan_steps() == [
        {"action": MACHINE_HOOKS_PLAN_ACTION, "target": "~/.claude/settings.json"},
        {"action": MACHINE_HOOKS_PLAN_ACTION, "target": "~/.codex/hooks.json"},
    ]


def test_apply_installs_and_reports_each_harness(tmp_path):
    (_home(tmp_path) / ".claude").mkdir(parents=True)
    (_home(tmp_path) / ".cursor").mkdir(parents=True)
    events, report = [], {}

    harness_posture_install.apply_machine_hooks(
        lambda action, target, status: events.append((action, target, status)), report
    )

    assert (MACHINE_HOOKS_PLAN_ACTION, "~/.claude/settings.json", "done") in events
    assert (MACHINE_HOOKS_PLAN_ACTION, "~/.cursor/hooks.json", "done") in events
    assert any(line.startswith("claude-code: installed ") for line in report["machine_hooks"])
    settings = json.loads((_home(tmp_path) / ".claude" / "settings.json").read_text())
    assert "SessionStart" in settings["hooks"]


def test_apply_reports_a_malformed_config_as_failed_with_recovery(tmp_path):
    claude = _home(tmp_path) / ".claude"
    claude.mkdir(parents=True)
    (claude / "settings.json").write_text("{broken")
    events, report = [], {}

    harness_posture_install.apply_machine_hooks(
        lambda action, target, status: events.append((action, target, status)), report
    )

    assert (MACHINE_HOOKS_PLAN_ACTION, "~/.claude/settings.json", "failed") in events
    [line] = report["machine_hooks"]
    assert "machine_hooks_config_malformed" in line
    assert "fix or move the file, then run `yoke setup` again" in line
    assert (claude / "settings.json").read_text() == "{broken"


def test_no_installed_harness_writes_nothing(tmp_path):
    events, report = [], {}
    harness_posture_install.apply_machine_hooks(
        lambda action, target, status: events.append((action, target, status)), report
    )
    assert events == [] and report["machine_hooks"] == []
    assert not _home(tmp_path).exists()
