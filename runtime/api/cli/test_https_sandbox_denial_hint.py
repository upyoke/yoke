"""Permission denial is conclusive; launcher identity does not diagnose DNS."""

from __future__ import annotations

import errno
import urllib.error

import pytest

from yoke_cli.transport import https_relay_outcome as outcome
from yoke_cli.transport.https_retry_policy import (
    connection_refusal_is_conclusive,
    is_sandbox_denial,
    should_retry_connection,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

API_URL = "https://app.example.test/api/orgs/acme"


def _denial() -> urllib.error.URLError:
    return urllib.error.URLError(
        PermissionError(errno.EPERM, "Operation not permitted")
    )


def _request() -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.get.run",
        request_id="00000000-0000-4000-8000-000000000000",
        actor=ActorContext(session_id="s"),
        target=TargetRef(kind="global"),
    )


def _hint(response) -> str:
    return response.error.recovery_hint


@pytest.mark.parametrize("code", [errno.EPERM, errno.EACCES])
def test_a_policy_refusal_is_conclusive_anywhere(code: int) -> None:
    error = urllib.error.URLError(PermissionError(code, "denied"))
    assert is_sandbox_denial(error) is True
    # Not loopback: the host is irrelevant, the policy is what refused.
    assert connection_refusal_is_conclusive(API_URL, error) is True
    assert should_retry_connection(0, API_URL, error) is False


def test_an_ordinary_refusal_is_not_a_sandbox_denial() -> None:
    error = urllib.error.URLError(ConnectionRefusedError(61, "Connection refused"))
    assert is_sandbox_denial(error) is False


def test_the_denial_hint_replaces_the_retry_advice() -> None:
    response = outcome.transport_error_response(
        _request(),
        API_URL,
        "could not reach",
        attempts=1,
        error=_denial(),
    )
    hint = _hint(response)
    assert "operating system denied permission" in hint
    assert "retrying will not help" in hint
    assert "Retrying is the repair" not in hint


@pytest.mark.parametrize("recovery", [None, "RECOVERY LINE."])
def test_unknown_reachability_does_not_infer_sandbox_cause(
    monkeypatch, recovery
) -> None:
    monkeypatch.setattr(outcome, "sandbox_recovery", lambda: recovery)
    hint = _hint(
        outcome.transport_error_response(
            _request(),
            API_URL,
            "could not reach",
            attempts=7,
        )
    )
    assert "cause is unknown" in hint
    assert "DNS" in hint
    assert "Retrying is the repair" in hint
    assert "sandbox" not in hint
    assert "RECOVERY LINE." not in hint
