"""Setup allows ``yoke`` machine-wide in every harness, even where the
operator kept their own mode, and uninstall removes exactly that entry.

Each case starts from a restrictive operator setup that existed before
Yoke: a prompting mode plus the operator's own allowlist.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from yoke_contracts import harness_settings_ledger as ledger
from yoke_contracts.harness_posture_install import configure_harness_unattended_posture
from yoke_contracts.harness_settings_revert import revert_recorded
from yoke_contracts.harness_unattended_posture import (
    POSTURE_PROMPTS,
    POSTURE_UNATTENDED,
    claude_settings_path,
    codex_config_path,
    cursor_config_path,
    posture_plan_summary,
)
from yoke_contracts.harness_yoke_allow import (
    CODEX_RULES_TEXT,
    YOKE_COMMAND_ALLOW,
    configure_yoke_allow,
    posture_state,
    yoke_allow_path,
    yoke_posture,
)

RESTRICTIVE_CLAUDE = {
    "theme": "dark",
    "permissions": {"defaultMode": "auto", "allow": ["Bash(ls:*)"]},
}
RESTRICTIVE_CURSOR = {
    "model": {"modelId": "grok"},
    "approvalMode": "allowlist",
    "sandbox": {"mode": "enabled"},
    "permissions": {"allow": ["Shell(ls)"], "deny": ["Shell(rm)"]},
}
RESTRICTIVE_CODEX = 'approval_policy = "on-request"\nsandbox_mode = "workspace-write"\n'


@pytest.fixture
def machine(tmp_path: Path, monkeypatch):
    """A home holding all three harnesses with restrictive operator config."""
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    monkeypatch.setenv("YOKE_HOME", str(tmp_path / ".yoke"))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    for path, text in (
        (claude_settings_path(), json.dumps(RESTRICTIVE_CLAUDE)),
        (cursor_config_path(), json.dumps(RESTRICTIVE_CURSOR)),
        (codex_config_path(), RESTRICTIVE_CODEX),
    ):
        path.parent.mkdir(parents=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def _json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def test_restrictive_harnesses_prompt_before_setup(machine):
    for harness in YOKE_COMMAND_ALLOW:
        assert posture_state(harness) == POSTURE_PROMPTS
        assert yoke_posture(harness).blocking


def test_setup_allows_yoke_and_keeps_every_operator_setting(machine):
    lines = configure_harness_unattended_posture(stream=io.StringIO())
    assert sum("allowed yoke in" in line for line in lines) == 3
    claude = _json(claude_settings_path())
    assert claude["permissions"]["defaultMode"] == "auto"
    assert claude["permissions"]["allow"] == ["Bash(ls:*)", "Bash(yoke:*)"]
    cursor = _json(cursor_config_path())
    assert cursor["approvalMode"] == "allowlist"
    assert cursor["permissions"] == {
        "allow": ["Shell(ls)", "Shell(yoke *)"],
        "deny": ["Shell(rm)"],
    }
    assert yoke_allow_path("codex").read_text() == CODEX_RULES_TEXT
    for harness in YOKE_COMMAND_ALLOW:
        verdict = yoke_posture(harness)
        assert verdict.blocking == () and verdict.kept, harness
        assert posture_state(harness) == POSTURE_UNATTENDED


def test_a_second_pass_changes_nothing(machine):
    configure_harness_unattended_posture(stream=io.StringIO())
    recorded = ledger.read()
    for harness in YOKE_COMMAND_ALLOW:
        assert configure_yoke_allow(harness) == []
    assert ledger.read() == recorded
    allow = _json(claude_settings_path())["permissions"]["allow"]
    assert allow.count("Bash(yoke:*)") == 1


def test_uninstall_removes_only_the_added_entries(machine):
    configure_harness_unattended_posture(stream=io.StringIO())
    lines, failures = revert_recorded()
    assert not failures, failures
    assert _json(claude_settings_path()) == RESTRICTIVE_CLAUDE
    assert _json(cursor_config_path()) == RESTRICTIVE_CURSOR
    assert codex_config_path().read_text() == RESTRICTIVE_CODEX
    assert not yoke_allow_path("codex").exists()
    assert not yoke_allow_path("codex").parent.exists()
    assert revert_recorded() == ([], [])


def test_containers_yoke_created_are_dropped_on_uninstall(machine):
    claude_settings_path().write_text('{"permissions": {"defaultMode": "auto"}}')
    cursor_config_path().write_text('{"approvalMode": "allowlist"}')
    configure_yoke_allow("claude-code")
    configure_yoke_allow("cursor")
    assert _json(cursor_config_path())["permissions"] == {
        "allow": ["Shell(yoke *)"],
        "deny": [],
    }
    revert_recorded()
    assert _json(claude_settings_path()) == {"permissions": {"defaultMode": "auto"}}
    assert _json(cursor_config_path()) == {"approvalMode": "allowlist"}


def test_an_entry_the_operator_removed_is_not_reinstated_by_uninstall(machine):
    configure_yoke_allow("cursor")
    payload = _json(cursor_config_path())
    payload["permissions"]["allow"].remove("Shell(yoke *)")
    cursor_config_path().write_text(json.dumps(payload))
    assert revert_recorded() == ([], [])
    assert _json(cursor_config_path()) == RESTRICTIVE_CURSOR


def test_a_malformed_allowlist_refuses_loudly_and_is_left_alone(machine):
    claude_settings_path().write_text('{"permissions": {"allow": "Bash(ls)"}}')
    (line,) = configure_yoke_allow("claude-code")
    assert "yoke_allow_failed" in line and "doctor run" in line
    assert _json(claude_settings_path()) == {"permissions": {"allow": "Bash(ls)"}}
    assert posture_state("claude-code") == POSTURE_PROMPTS


def test_an_operator_codex_rules_file_with_the_same_name_is_kept(machine):
    rules = yoke_allow_path("codex")
    rules.parent.mkdir()
    rules.write_text('prefix_rule(pattern = ["ls"])\n')
    (line,) = configure_yoke_allow("codex")
    assert "yoke_allow_failed" in line
    assert rules.read_text() == 'prefix_rule(pattern = ["ls"])\n'


def test_absent_harnesses_are_skipped(tmp_path, monkeypatch):
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.delenv("CODEX_HOME", raising=False)
    for harness in YOKE_COMMAND_ALLOW:
        assert configure_yoke_allow(harness) == []
        assert yoke_posture(harness) is None


def test_claude_surface_selects_its_own_mode(machine):
    configure_yoke_allow("claude-code")
    assert yoke_posture("claude-code", "claude-cli").kept
    settings = _json(claude_settings_path())
    settings["permissions"]["allow"] = []
    claude_settings_path().write_text(json.dumps(settings))
    assert yoke_posture("claude-code", "claude-cli").blocking


def test_review_summary_names_every_allow_entry(machine):
    summary = posture_plan_summary()
    for entry in YOKE_COMMAND_ALLOW.values():
        assert entry in summary
