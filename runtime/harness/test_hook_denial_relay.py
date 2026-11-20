"""Coverage for the client-local denial's HTTPS audit relay.

``local_subset.py`` cannot record ``HarnessToolCallDenied`` itself (the
client/server package boundary forbids any ``yoke_core`` import), so
``relay_denial_audit`` is the client-side leg that POSTs the audit fields
``local_subset.py`` handed back to the server's denial-audit sink.
"""

from __future__ import annotations

from unittest import mock

from yoke_cli.transport.https import HttpsConnection
from yoke_harness.hooks.deadline import HookDeadline
from yoke_harness.hooks.denial_relay import (
    AUDIT_TIMEOUT_MS,
    DENIAL_AUDIT_PATH,
    hold_denial_audits,
    relay_denial_audit,
    send_held_denial_audits,
    submit_denial_audit,
)


def _connection() -> HttpsConnection:
    return HttpsConnection(api_url="https://example.test", token="tok")


def test_empty_audit_never_makes_a_request() -> None:
    with mock.patch("yoke_harness.hooks.denial_relay.request_json") as post:
        relay_denial_audit(_connection(), {})
    post.assert_not_called()


def test_posts_audit_to_the_denial_audit_path() -> None:
    audit = {"hook": "yoke_core.domain.lint_destructive_git", "mode": "deny"}
    with mock.patch("yoke_harness.hooks.denial_relay.request_json") as post:
        relay_denial_audit(_connection(), audit)
    post.assert_called_once()
    request = post.call_args.args[0]
    assert request.full_url == f"https://example.test{DENIAL_AUDIT_PATH}"
    assert request.get_header("Authorization") == "Bearer tok"


def test_transport_failure_never_raises() -> None:
    with mock.patch(
        "yoke_harness.hooks.denial_relay.request_json", side_effect=RuntimeError("boom"),
    ):
        relay_denial_audit(_connection(), {"hook": "x"})


def _deadline(remaining_ms: int) -> HookDeadline:
    return HookDeadline(budget_ms=remaining_ms, started_at=0.0, clock=lambda: 0.0)


def test_held_audit_posts_only_when_released() -> None:
    with mock.patch("yoke_harness.hooks.denial_relay.request_json") as post:
        token = hold_denial_audits()
        submit_denial_audit(_connection(), {"hook": "x"}, _deadline(10))
        post.assert_not_called()
        send_held_denial_audits(token)
    post.assert_called_once()
    assert post.call_args.kwargs["timeout_seconds"] == AUDIT_TIMEOUT_MS / 1000


def test_released_hold_restores_direct_posting() -> None:
    send_held_denial_audits(hold_denial_audits())
    with mock.patch("yoke_harness.hooks.denial_relay.request_json") as post:
        submit_denial_audit(_connection(), {"hook": "x"}, _deadline(5000))
    post.assert_called_once()


def test_unheld_audit_spends_only_the_remaining_hook_budget() -> None:
    with mock.patch("yoke_harness.hooks.denial_relay.request_json") as post:
        submit_denial_audit(_connection(), {"hook": "x"}, _deadline(400))
    assert post.call_args.kwargs["timeout_seconds"] == 0.4


def test_unheld_audit_is_not_posted_once_the_budget_is_spent() -> None:
    with mock.patch("yoke_harness.hooks.denial_relay.request_json") as post:
        submit_denial_audit(_connection(), {"hook": "x"}, _deadline(0))
    post.assert_not_called()
