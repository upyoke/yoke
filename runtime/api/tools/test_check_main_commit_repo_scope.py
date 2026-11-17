"""The main-commit scope probe reads every harness's deny wire shape."""

import json
import subprocess

import pytest

from runtime.api.tools.check_main_commit_repo_scope import (
    foreign_refs,
    hook_verdict,
    item_lane_roots,
)

REASON = "BLOCKED: Implementation commit on main branch.\n  - YOK-1: x"


def _result(returncode, stdout="", stderr=""):
    return subprocess.CompletedProcess([], returncode, stdout, stderr)


def test_codex_json_deny_on_exit_zero_is_denied():
    body = {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": REASON,
    }}
    assert hook_verdict(_result(0, json.dumps(body))) == (True, REASON)


def test_cursor_json_deny_on_exit_zero_is_denied():
    body = {"permission": "deny", "user_message": REASON, "agent_message": REASON}
    assert hook_verdict(_result(0, json.dumps(body))) == (True, REASON)


def test_claude_exit_two_is_denied_with_stderr_reason():
    assert hook_verdict(_result(2, stderr=REASON)) == (True, REASON)


def test_empty_and_context_only_output_allow():
    context = {"hookSpecificOutput": {"additionalContext": "note"}}
    assert hook_verdict(_result(0)) == (False, "")
    assert hook_verdict(_result(0, json.dumps(context))) == (False, "")


@pytest.mark.parametrize("result", [_result(1, stderr="boom"), _result(0, "not json")])
def test_crash_or_garbled_output_refuses(result):
    with pytest.raises(RuntimeError, match="rerun"):
        hook_verdict(result)


def _item(*lanes):
    return {"worktrees": [
        {"path": path, "state": state, "released_at": None} for path, state in lanes
    ]}


def test_lane_roots_skip_inactive_and_normalize_windows():
    item = _item(("C:\\x\\repo\\.worktrees\\YOK-1", "active"), ("/r/.worktrees/YOK-1", "released"))
    assert item_lane_roots(item) == {"c:/x/repo"}


def test_foreign_refs_flags_items_whose_lanes_live_in_other_repos(tmp_path):
    root = tmp_path / "repo"
    (root / ".worktrees" / "YOK-1").mkdir(parents=True)
    items = {
        "YOK-1": _item((str(root / ".worktrees" / "YOK-1"), "active")),
        "YOK-2": _item(("/elsewhere/.worktrees/YOK-2", "active")),
    }
    assert foreign_refs(["YOK-1", "YOK-2"], root, items.__getitem__) == ["YOK-2"]
