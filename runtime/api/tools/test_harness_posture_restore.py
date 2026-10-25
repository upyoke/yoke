"""Setup enforces unattended modes; uninstall restores prior settings.

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
)
from yoke_contracts.harness_posture_read import posture_findings, posture_state


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
    for harness in ("claude-code", "codex", "cursor"):
        assert posture_state(harness) == POSTURE_PROMPTS
        assert posture_findings(harness)


def test_setup_enforces_posture_and_keeps_unrelated_settings(machine):
    lines = configure_harness_unattended_posture(stream=io.StringIO())
    assert len(lines) == 3
    claude = _json(claude_settings_path())
    assert claude["permissions"]["defaultMode"] == "bypassPermissions"
    assert claude["permissions"]["allow"] == ["Bash(ls:*)"]
    cursor = _json(cursor_config_path())
    assert cursor["approvalMode"] == "unrestricted"
    assert cursor["permissions"] == {
        "allow": ["Shell(ls)"],
        "deny": ["Shell(rm)"],
    }
    assert not (codex_config_path().parent / "rules/yoke.rules").exists()
    for harness in ("claude-code", "codex", "cursor"):
        assert posture_findings(harness) == (), harness
        assert posture_state(harness) == POSTURE_UNATTENDED


def test_a_second_pass_changes_nothing(machine):
    configure_harness_unattended_posture(stream=io.StringIO())
    recorded = ledger.read()
    assert configure_harness_unattended_posture(stream=io.StringIO()) == []
    assert ledger.read() == recorded


def test_uninstall_restores_original_modes(machine):
    configure_harness_unattended_posture(stream=io.StringIO())
    lines, failures = revert_recorded()
    assert not failures, failures
    assert _json(claude_settings_path()) == RESTRICTIVE_CLAUDE
    assert _json(cursor_config_path()) == RESTRICTIVE_CURSOR
    assert codex_config_path().read_text() == RESTRICTIVE_CODEX
    assert revert_recorded() == ([], [])


@pytest.mark.parametrize(
    "assignment",
    [
        '"approval_policy" = "on-request" # keep this comment\n',
        "approval_policy = '''on-request'''\n",
        'approval_policy = """\non-request"""\n',
    ],
)
def test_codex_uninstall_restores_original_assignment(machine, assignment):
    original = assignment + 'sandbox_mode = "read-only"\nmodel = "chosen"\n'
    codex_config_path().write_text(original)
    configure_harness_unattended_posture(stream=io.StringIO())
    assert posture_state("codex") == POSTURE_UNATTENDED
    assert revert_recorded()[1] == []
    assert codex_config_path().read_text() == original


def test_repair_remembers_the_latest_operator_mode(machine):
    configure_harness_unattended_posture(stream=io.StringIO())
    config = _json(claude_settings_path())
    config["permissions"]["defaultMode"] = "plan"
    claude_settings_path().write_text(json.dumps(config))
    configure_harness_unattended_posture(stream=io.StringIO())
    assert (
        _json(claude_settings_path())["permissions"]["defaultMode"]
        == "bypassPermissions"
    )
    assert revert_recorded()[1] == []
    assert _json(claude_settings_path())["permissions"]["defaultMode"] == "plan"
