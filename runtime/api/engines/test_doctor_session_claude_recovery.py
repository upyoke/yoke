"""A restricted Claude session is told an action it can actually take.

Claude Code puts bypass permissions in the Shift+Tab cycle only for a session
launched with it enabled. When ``~/.claude/settings.json`` no longer starts
sessions in ``bypassPermissions`` (Claude Code offers once to switch the
default to ``auto``), the recovery repairs the default and starts a new
session instead of naming an unreachable mode switch.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.testing.real_home_isolation import set_home
from yoke_contracts.harness_session_permission_posture import (
    CLAUDE_SESSION_PERMISSION_POSTURE as POSTURE,
)
from yoke_contracts.harness_unattended_posture import claude_settings_path
from yoke_core.engines.doctor_session_posture import session_posture
from yoke_harness.hooks.session_permission_mode import capture_permission_mode

ROOT = Path(__file__).resolve().parents[3]
SESSION = "22222222-2222-4222-8222-222222222222"


@pytest.fixture
def session(tmp_path, monkeypatch):
    set_home(monkeypatch, tmp_path)
    claude_settings_path().parent.mkdir(parents=True)
    capture_permission_mode(
        {"session_id": SESSION, "permission_mode": "auto"}, "claude-code"
    )
    return SESSION


def _default(mode):
    permissions = {} if mode is None else {"defaultMode": mode}
    claude_settings_path().write_text(json.dumps({"permissions": permissions}))


@pytest.mark.parametrize("mode", ["auto", None])
def test_a_lost_default_names_the_repair_and_a_new_session(session, mode):
    _default(mode)
    verdict, detail = session_posture("claude-code", "claude-cli", session_id=session)
    assert verdict == "FAIL"
    assert detail.startswith("HARNESS_POSTURE_RESTRICTED: this session is in 'auto'")
    assert f"is {mode!r}" in detail
    assert "Not available: Shift+Tab cannot reach bypass permissions" in detail
    assert "`yoke doctor run --only harness-setup --fix`" in detail
    assert POSTURE.launch_command in detail
    assert "select bypass permissions in this chat" not in detail


def test_a_bypass_default_names_the_mode_cycle(session):
    _default("bypassPermissions")
    verdict, detail = session_posture("claude-code", "claude-cli", session_id=session)
    assert verdict == "FAIL"
    assert "Not available" not in detail
    assert POSTURE.surface_recovery["claude-cli"].rstrip(".") in detail


@pytest.mark.parametrize("surface", ["claude-desktop", "claude-vscode"])
def test_other_surfaces_use_their_own_recovery(session, surface):
    _default("auto")
    _verdict, detail = session_posture("claude-code", surface, session_id=session)
    assert POSTURE.surface_recovery[surface].rstrip(".") in detail
    assert "Not available" not in detail


def test_the_manifest_carries_the_contract():
    manifest = ROOT / "runtime" / "harness" / "claude" / "manifest.json"
    rendered = json.loads(manifest.read_text(encoding="utf-8"))
    assert rendered["session_permission_posture"] == POSTURE.to_json()
