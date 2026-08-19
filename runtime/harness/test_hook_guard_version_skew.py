"""Relayed guard denials expose client/server revision skew."""

from __future__ import annotations

import json

from yoke_harness.hooks.guard_version_skew import (
    annotate_guard_version_skew,
    guard_version_skew_notice,
)


CLIENT = {"source_sha": "a" * 40}
SERVER = {"source_sha": "b" * 40}


def test_matching_full_and_short_revisions_need_no_notice() -> None:
    assert (
        guard_version_skew_notice(
            client=CLIENT,
            server={"source_sha": "a" * 12},
        )
        == ""
    )
    assert (
        guard_version_skew_notice(
            client=CLIENT,
            server={"source_sha": "unknown"},
        )
        == ""
    )


def test_mismatch_notice_names_serving_process_restart_boundary() -> None:
    notice = guard_version_skew_notice(client=CLIENT, server=SERVER)
    assert "server revision bbbbbbbbbbbb" in notice
    assert "client hook is running aaaaaaaaaaaa" in notice
    assert "serving Yoke process" in notice
    assert "Restarting only this harness session" in notice


def test_codex_deny_reason_receives_skew_notice_once() -> None:
    stdout = json.dumps(
        {
            "hookSpecificOutput": {
                "hookEventName": "PreToolUse",
                "permissionDecision": "deny",
                "permissionDecisionReason": "original refusal",
            }
        }
    )
    annotated = annotate_guard_version_skew(
        stdout,
        client=CLIENT,
        server=SERVER,
    )
    repeated = annotate_guard_version_skew(
        annotated,
        client=CLIENT,
        server=SERVER,
    )
    reason = json.loads(repeated)["hookSpecificOutput"]["permissionDecisionReason"]
    assert reason.startswith("original refusal")
    assert reason.count("Yoke guard version mismatch:") == 1


def test_cursor_deny_updates_both_visible_messages() -> None:
    stdout = json.dumps(
        {
            "permission": "deny",
            "user_message": "user refusal",
            "agent_message": "agent refusal",
        }
    )
    payload = json.loads(
        annotate_guard_version_skew(
            stdout,
            client=CLIENT,
            server=SERVER,
        )
    )
    assert "guard version mismatch" in payload["user_message"]
    assert "guard version mismatch" in payload["agent_message"]


def test_plain_claude_refusal_receives_skew_notice() -> None:
    annotated = annotate_guard_version_skew(
        "plain refusal\n",
        client=CLIENT,
        server=SERVER,
    )
    assert annotated.startswith("plain refusal\n\n")
    assert "Yoke guard version mismatch:" in annotated


def test_unrecognized_json_is_preserved_as_valid_wire_output() -> None:
    stdout = json.dumps({"permission": "ask"})
    assert (
        annotate_guard_version_skew(
            stdout,
            client=CLIENT,
            server=SERVER,
        )
        == stdout
    )
