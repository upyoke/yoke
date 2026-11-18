"""Uninstall leaves ``~/.claude/settings.json`` exactly as it was before Yoke.

Claude Code answers Yoke's ``bypassPermissions`` default on its own: it may
rewrite the default to ``auto`` after asking once, and it records
``skipDangerousModePermissionPrompt`` when a person accepts the bypass
warning. Both exist only because of Yoke's write, so uninstall removes them,
along with the ``hooks`` object and the file Yoke created.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

import pytest

from yoke_contracts import harness_settings_ledger as ledger
from yoke_contracts.claude_posture_install import configure_claude_cli_permission_mode
from yoke_contracts.harness_settings_revert import revert_recorded
from yoke_contracts.harness_unattended_posture import claude_settings_path
from yoke_harness.hooks.machine_hooks import ensure_machine_hooks, remove_machine_hooks

FRESH = {"theme": "dark"}


@pytest.fixture
def home(tmp_path: Path, monkeypatch) -> Path:
    monkeypatch.setenv("HOME", str(tmp_path))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / ".config"))
    claude_settings_path().parent.mkdir(parents=True)
    return tmp_path


def _setup() -> None:
    configure_claude_cli_permission_mode(stream=io.StringIO())
    ensure_machine_hooks(["claude-code"])


def _uninstall() -> list[str]:
    remove_machine_hooks()
    lines, failures = revert_recorded()
    assert failures == []
    return lines


def _read() -> dict:
    return json.loads(claude_settings_path().read_text(encoding="utf-8"))


def _claude_answers(*, accept_auto: bool) -> None:
    """What Claude Code writes on the first interactive launch after setup."""
    settings = _read()
    settings["skipDangerousModePermissionPrompt"] = True
    if accept_auto:
        settings["permissions"]["defaultMode"] = "auto"
    claude_settings_path().write_text(json.dumps(settings), encoding="utf-8")


@pytest.mark.parametrize("accept_auto", [True, False])
def test_uninstall_restores_a_file_without_permissions(home, accept_auto):
    claude_settings_path().write_text(json.dumps(FRESH), encoding="utf-8")
    _setup()
    assert _read()["permissions"] == {"defaultMode": "bypassPermissions"}
    assert "hooks" in _read()
    _claude_answers(accept_auto=accept_auto)
    lines = _uninstall()
    assert _read() == FRESH
    assert any("removed permissions.defaultMode" in line for line in lines)
    assert not any("left your setting in place" in line for line in lines)


def test_a_repair_after_claude_switched_to_auto_still_restores_nothing(home):
    claude_settings_path().write_text(json.dumps(FRESH), encoding="utf-8")
    _setup()
    _claude_answers(accept_auto=True)
    configure_claude_cli_permission_mode(stream=io.StringIO())
    assert _read()["permissions"]["defaultMode"] == "bypassPermissions"
    _uninstall()
    assert _read() == FRESH


def test_uninstall_removes_the_settings_file_yoke_created(home):
    _setup()
    _claude_answers(accept_auto=True)
    _uninstall()
    assert not claude_settings_path().exists()


def test_a_preexisting_empty_hooks_object_and_acceptance_stay(home):
    original = {"hooks": {}, "skipDangerousModePermissionPrompt": True}
    claude_settings_path().write_text(json.dumps(original), encoding="utf-8")
    _setup()
    _uninstall()
    assert _read() == original


def test_an_operator_mode_chosen_after_setup_is_remembered(home):
    claude_settings_path().write_text(json.dumps(FRESH), encoding="utf-8")
    _setup()
    settings = _read()
    settings["permissions"]["defaultMode"] = "plan"
    claude_settings_path().write_text(json.dumps(settings), encoding="utf-8")
    configure_claude_cli_permission_mode(stream=io.StringIO())
    _uninstall()
    assert _read() == {**FRESH, "permissions": {"defaultMode": "plan"}}


def test_the_rewrite_is_recorded_beside_yokes_value(home):
    claude_settings_path().write_text(json.dumps(FRESH), encoding="utf-8")
    configure_claude_cli_permission_mode(stream=io.StringIO())
    (mode,) = [
        e for e in ledger.read() if e.get("keys") == ["permissions", "defaultMode"]
    ]
    assert mode["value"] == "bypassPermissions"
    assert mode["derived"] == ["auto"]
    assert "previous" not in mode
