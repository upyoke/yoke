"""A control-plane call an OS sandbox refused says so, and stops retrying.

Two distinct shapes reach the same conclusion. A connect the kernel refused
on policy carries EPERM, which is conclusive: the policy that blocked it
blocks every retry, so spending the budget only makes the wait longer before
the same verdict. A denied *name lookup* is indistinguishable from a host
that is genuinely unreachable, so it keeps its retries — but under a harness
that sandboxes commands the hint says to check that first, because "retrying
is the repair" is the one piece of advice that can never work there.
"""

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
    return urllib.error.URLError(PermissionError(errno.EPERM, "Operation not permitted"))


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
        _request(), API_URL, "could not reach", attempts=1, error=_denial(),
    )
    hint = _hint(response)
    assert "sandbox policy" in hint
    assert "retrying will not help" in hint
    assert "Retrying is the repair" not in hint


def test_an_unreachable_relay_under_a_sandboxing_harness_names_it(
    monkeypatch,
) -> None:
    monkeypatch.setattr(outcome, "sandbox_recovery", lambda: "RECOVERY LINE.")
    hint = _hint(
        outcome.transport_error_response(
            _request(), API_URL, "could not reach", attempts=7,
        )
    )
    assert "sandboxes commands" in hint
    assert "RECOVERY LINE." in hint
    assert "Retrying is the repair" not in hint


def test_an_unreachable_relay_outside_a_harness_keeps_the_old_advice(
    monkeypatch,
) -> None:
    monkeypatch.setattr(outcome, "sandbox_recovery", lambda: None)
    hint = _hint(
        outcome.transport_error_response(
            _request(), API_URL, "could not reach", attempts=7,
        )
    )
    assert "Retrying is the repair" in hint
    assert "sandboxes commands" not in hint
