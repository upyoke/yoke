"""Claude SessionEnd hooks carry an explicit budget past Claude's 1.5 s exit cap."""

import json
from pathlib import Path

from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS
from yoke_contracts.machine_hooks_render import (
    CLAUDE_SESSION_END_HOOK_TIMEOUT_S,
    render_user_hook_entries,
)
from yoke_contracts.project_contract.hook_entries import converge_event_entries
from yoke_core.domain.agents_render_claude import render_claude_settings_json
from yoke_core.domain.agents_render_hooks import render_claude_hooks_block

REPO_ROOT = Path(__file__).resolve().parents[3]


def _timeouts(block: dict) -> dict[str, set]:
    return {
        event: {
            handler.get("timeout")
            for entry in entries
            for handler in entry.get("hooks") or []
        }
        for event, entries in block.items()
    }


def test_only_session_end_gains_a_timeout_in_both_layers() -> None:
    assert CLAUDE_SESSION_END_HOOK_TIMEOUT_S == 15
    for block in (
        render_claude_hooks_block(),
        render_user_hook_entries(HARNESS_MACHINE_HOOKS["claude-code"]),
    ):
        timeouts = _timeouts(block)
        assert timeouts.pop("SessionEnd") == {15}
        assert timeouts and all(value == {None} for value in timeouts.values())


def test_committed_claude_settings_match_the_render() -> None:
    rendered = render_claude_settings_json()
    for rel in ("runtime/harness/claude/settings.json", ".claude/settings.json"):
        assert (REPO_ROOT / rel).read_text(encoding="utf-8") == rendered, rel
    assert json.loads(rendered)["hooks"]["SessionEnd"][0]["hooks"][0]["timeout"] == 15


def test_upgrade_replaces_the_old_session_end_entry_in_place() -> None:
    provided = render_claude_hooks_block()["SessionEnd"]
    old = json.loads(json.dumps(provided))
    old[0]["hooks"][0].pop("timeout")
    operator = {"hooks": [{"type": "command", "command": "echo mine"}]}
    entries = [operator, *old]

    added, replaced = converge_event_entries("SessionEnd", entries, provided)

    assert entries == [operator, *provided]
    assert entries[1]["hooks"][0]["timeout"] == 15
    assert len(added) == len(replaced) == 1
    assert converge_event_entries("SessionEnd", entries, provided) == ([], [])
