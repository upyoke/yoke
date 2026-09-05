"""The bounded app-server client keeps a peer RPC error's real detail.

field-note 46471: request() used to collapse every JSON-RPC ``error``
payload into ``code="method_error"``, discarding the peer's own code and
message, and session_relay_codex_plan_limit.py then read that one code as
"unsupported_on_this_build" regardless of what actually failed. Only a
``-32601`` ("method not found") is now treated as evidence of an
unsupported operation; every other RPC error keeps its own code and a
redacted copy of its message via ``_rpc_error``.
"""

from __future__ import annotations

import tempfile

from yoke_harness import session_relay_codex_plan_limit as codex_limits
from yoke_harness.session_relay_codex_app_server_client import _Client, _rpc_error


def test_a_method_not_found_rpc_error_is_the_true_unsupported_signal() -> None:
    """The one peer response that actually means this build lacks the op."""
    failure = _rpc_error(
        "account/rateLimits/read",
        "handshake",
        {"code": -32601, "message": "no such method"},
    )
    assert failure.code == "method_error"
    assert failure.rpc_error_code == -32601
    assert "no such method" in str(failure)


def test_an_unrelated_rpc_error_keeps_its_own_code_instead_of_unsupported() -> None:
    failure = _rpc_error(
        "account/rateLimits/read",
        "handshake",
        {"code": -32001, "message": "Not authenticated"},
    )
    assert failure.code == "rpc_error"
    assert failure.rpc_error_code == -32001
    assert "Not authenticated" in str(failure)
    assert codex_limits._failure_reason(failure) == "app_server_rpc_error:-32001"


def test_an_rpc_error_with_no_code_still_avoids_the_unsupported_reading() -> None:
    failure = _rpc_error("account/rateLimits/read", "handshake", {"message": "boom"})
    assert failure.code == "rpc_error"
    assert failure.rpc_error_code is None
    assert codex_limits._failure_reason(failure) == "app_server_rpc_error"


def test_an_rpc_error_message_is_redacted_before_it_is_surfaced() -> None:
    token = "yoke_v1_" + "a" * 43
    failure = _rpc_error(
        "account/rateLimits/read",
        "handshake",
        {"code": -32001, "message": f"denied for token {token}"},
    )
    assert token not in str(failure)
    assert "[Yoke API token redacted]" in str(failure)


def test_the_client_keeps_the_failing_child_stderr_tail() -> None:
    client = object.__new__(_Client)
    client.stderr_file = tempfile.TemporaryFile()
    client.stderr_file.write(b"codex: app-server refused the connection\n")

    assert "refused the connection" in client.stderr_tail()


def test_the_client_redacts_a_token_from_the_stderr_tail() -> None:
    token = "yoke_v1_" + "b" * 43
    client = object.__new__(_Client)
    client.stderr_file = tempfile.TemporaryFile()
    client.stderr_file.write(f"codex: denied for {token}".encode())

    tail = client.stderr_tail()

    assert token not in tail
    assert "[Yoke API token redacted]" in tail


def test_the_client_reports_no_tail_when_capture_is_off() -> None:
    client = object.__new__(_Client)
    client.stderr_file = None

    assert client.stderr_tail() == ""
