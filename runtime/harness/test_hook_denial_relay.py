"""Coverage for the client-local denial's fire-and-forget HTTPS relay.

``local_subset.py`` cannot record ``HarnessToolCallDenied`` itself (the
client/server package boundary forbids any ``yoke_core`` import), so
``relay_denial_audit`` is the client-side leg that POSTs the audit fields
``local_subset.py`` handed back to the server's denial-audit sink.
"""

from __future__ import annotations

from unittest import mock

from yoke_cli.transport.https import HttpsConnection
from yoke_harness.hooks.denial_relay import DENIAL_AUDIT_PATH, relay_denial_audit


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
