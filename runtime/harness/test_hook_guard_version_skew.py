"""Relayed guard denials expose client/server revision skew."""

from __future__ import annotations

import json

from yoke_contracts.execution_provenance import collect_execution_provenance
from yoke_harness.hooks.guard_version_skew import (
    annotate_guard_version_skew,
    guard_version_skew_notice,
)


def _provenance(sha: str, module_file: str) -> dict:
    """Real provenance for one install shape, rather than a hand-built dict.

    ``install_kind`` is what the recovery branches on, so the fixtures have to
    come from the collector that populates it in production — a literal dict
    would let the two drift apart without a test noticing.
    """
    return collect_execution_provenance(
        module_file=module_file,
        env={"YOKE_BUILD_SHA": sha},
    )


#: This test file sits in a checkout, so the collector reports a git tree.
CLIENT = _provenance("a" * 40, __file__)
SERVER_FROM_CHECKOUT = _provenance("b" * 40, __file__)
#: No ``.git`` above a ``site-packages`` parent, so the collector reports a
#: build whose files were copied in rather than a tree it can re-read.
SERVER = _provenance("b" * 40, "/opt/py/site-packages/yoke_harness/hooks/x.py")
SERVER_FROM_UV_TOOL = _provenance(
    "b" * 40, "/Users/me/.local/share/uv/tools/yoke/lib/yoke_harness/x.py"
)


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


def test_the_recovery_differs_by_how_the_server_was_installed() -> None:
    """Provenance is captured once at import, so what moves a server off its
    revision depends on where it loaded code from: a checkout re-reads its tree
    on restart, an installed build re-imports the same artifact. The footer used
    to give one unconditional answer, which is wrong for one of the two."""
    from_checkout = guard_version_skew_notice(
        client=CLIENT, server=SERVER_FROM_CHECKOUT
    )
    installed = guard_version_skew_notice(client=CLIENT, server=SERVER)
    assert from_checkout and installed
    assert from_checkout != installed


def test_a_checkout_server_is_told_which_tree_a_restart_would_re_read() -> None:
    """The action is only actionable if it names the tree it applies to, and
    that path has to come from the server's own provenance."""
    notice = guard_version_skew_notice(client=CLIENT, server=SERVER_FROM_CHECKOUT)
    assert SERVER_FROM_CHECKOUT["install_path"] in notice


def test_a_build_server_is_not_told_to_re_read_a_tree_it_does_not_have() -> None:
    """It has no checkout to re-probe, so it must not be handed the checkout
    recovery — and must not be told some other server's path."""
    notice = guard_version_skew_notice(client=CLIENT, server=SERVER)
    assert SERVER["install_path"] not in notice
    assert notice != guard_version_skew_notice(
        client=CLIENT, server=SERVER_FROM_CHECKOUT
    )


def test_an_install_kind_that_is_not_a_checkout_gets_the_build_recovery() -> None:
    """Only a checkout is known to re-probe on restart. Every other shape gets
    the conservative answer rather than an action that may do nothing."""
    assert SERVER_FROM_UV_TOOL["install_kind"] != "source_checkout"
    assert guard_version_skew_notice(
        client=CLIENT, server=SERVER_FROM_UV_TOOL
    ) == guard_version_skew_notice(client=CLIENT, server=SERVER)


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
