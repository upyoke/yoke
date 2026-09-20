"""Relayed guard denials expose client/server revision skew."""

from __future__ import annotations

import json

from yoke_harness.hooks.guard_version_skew import (
    annotate_guard_version_skew,
    guard_version_skew_notice,
)


CLIENT = {"source_sha": "a" * 40, "install_kind": "source_checkout"}
SERVER = {"source_sha": "b" * 40, "install_kind": "installed_wheel"}
SERVER_FROM_CHECKOUT = {
    "source_sha": "b" * 40,
    "install_kind": "source_checkout",
    "install_path": "/srv/yoke",
}


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


def test_mismatch_notice_names_both_revisions() -> None:
    notice = guard_version_skew_notice(client=CLIENT, server=SERVER)
    assert "server revision bbbbbbbbbbbb" in notice
    assert "client hook is aaaaaaaaaaaa" in notice


def test_an_installed_server_is_told_a_restart_does_not_close_the_gap() -> None:
    """Provenance is captured once at import. Restarting a process that loaded
    an installed artifact re-imports that same artifact, so the only thing that
    moves it is installing a newer build."""
    notice = guard_version_skew_notice(client=CLIENT, server=SERVER)
    assert "installed build" in notice
    assert "installed" in notice
    assert "restart" in notice.lower()
    # The old wording named a restart as the remedy for every case.
    assert not notice.endswith(
        "restart the serving Yoke process at the intended revision."
    )


def test_a_source_checkout_server_is_told_a_restart_does_close_the_gap() -> None:
    """There the loaded modules came from a git tree that has since moved, so a
    restart re-probes that tree and picks the new revision up."""
    notice = guard_version_skew_notice(client=CLIENT, server=SERVER_FROM_CHECKOUT)
    assert "restart" in notice.lower()
    assert "/srv/yoke" in notice
    assert "installed build" not in notice


def test_an_unknown_install_kind_is_not_promised_a_restart_remedy() -> None:
    """Only a checkout is known to re-probe, so anything else gets the
    conservative recovery rather than an action that may do nothing."""
    notice = guard_version_skew_notice(
        client=CLIENT, server={"source_sha": "b" * 40, "install_kind": "uv_tool"},
    )
    assert "installed build" in notice


def test_mismatch_notice_is_one_line() -> None:
    """It rides along on a refusal the reader is already diagnosing."""
    for server in (SERVER, SERVER_FROM_CHECKOUT):
        notice = guard_version_skew_notice(client=CLIENT, server=server)
        assert notice.count("\n") == 0


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
