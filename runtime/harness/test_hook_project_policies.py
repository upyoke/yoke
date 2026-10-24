"""Real hook-chain policy behavior in a registered workspace."""

import pytest

from yoke_contracts.field_note_text import DENIAL_FOOTER

from runtime.harness.test_hook_project_scope import project_map as project_map
from runtime.harness.test_hook_runner import _silence_telemetry
from yoke_core.hooks.claude_adapter import CAPABILITY as CLAUDE_CAPABILITY
from yoke_core.hooks import runner as runner_module
from yoke_core.hooks.adapter_capability import AdapterCapability


def test_real_chain_pretool_bash_sqlite3_denies(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path,
    project_map,
) -> None:
    """The real PreToolUse Bash chain denies a raw ``sqlite3`` invocation."""
    project_map["connection_projects"]["local"] = [
        {"checkout": str(tmp_path), "project_id": 1}
    ]
    _silence_telemetry(monkeypatch)
    payload = {
        "tool_name": "Bash",
        "tool_input": {"command": 'sqlite3 data/yoke.db "SELECT 1"'},
        "session_id": "sess-smoke",
        "cwd": str(tmp_path),
    }

    capability = AdapterCapability(
        family="claude",
        payload_parser=lambda raw: payload,
        decision_renderer=CLAUDE_CAPABILITY.decision_renderer,
        subprocess_modules=CLAUDE_CAPABILITY.subprocess_modules,
        apply_patch_chain_omissions=CLAUDE_CAPABILITY.apply_patch_chain_omissions,
        pretool_omissions=CLAUDE_CAPABILITY.pretool_omissions,
    )

    text, exit_code = runner_module.run_event(
        "PreToolUse",
        capability=capability,
        stdin_data="{}",
    )

    # The adapter returns Claude's plain blocking narrative with exit code 2.
    assert exit_code == 2, f"expected deny exit 2, got {exit_code}; text={text!r}"
    assert text.startswith("BLOCKED: Do not call sqlite3 directly.")
    assert DENIAL_FOOTER in text
    assert text.endswith("Yoke check id: lint-sqlite-cmd")
    assert "hookSpecificOutput" not in text
