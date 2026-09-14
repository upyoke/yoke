"""How many tries one relay call is allowed, and who decides.

Two answers used to live in the relay loop as expressions: the clamp that
turned a caller's requested attempt count into a budget, and the rule that
gives a server still working on an accepted envelope exactly one more try.
Both are "is another attempt worth it" questions, so both belong to the
retry policy — and the clamp had a bug worth pinning down, because reading
a requested zero as "unstated" spent the full connection ladder on a caller
that asked for none of it.
"""

from __future__ import annotations

import pytest

from runtime.api.cli.https_relay_security_test_support import (
    CONNECTION,
    FakeResponse,
    envelope,
    sensitive_request,
)
from yoke_cli.transport import https as relay_module
from yoke_cli.transport import https_retry_policy
from yoke_cli.transport.https_retry_policy import (
    CONNECTION_ATTEMPTS,
    RESPONSE_DEADLINE_ATTEMPTS,
    attempt_budget,
    should_retry_response_deadline,
)
from yoke_cli.transport.response_deadline_errors import ResponseOpenDeadlineError


@pytest.fixture(autouse=True)
def _no_telemetry(monkeypatch):
    """Outcome recording has its own module and its own tests."""
    monkeypatch.setattr(relay_module, "record_outcome", lambda *_a, **_k: None)


def _relay(monkeypatch, openers, sleeps, *, max_attempts=None):
    calls = {"count": 0}

    def _open(_request, *, deadline, timeout_s):
        index = calls["count"]
        calls["count"] += 1
        outcome = openers[min(index, len(openers) - 1)]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    monkeypatch.setattr(relay_module, "_open_function_relay", _open)
    response = relay_module.relay_https(
        sensitive_request(),
        CONNECTION,
        sleep=sleeps.append,
        max_attempts=max_attempts,
    )
    return response, calls["count"]


def test_an_unstated_budget_takes_the_whole_connection_ladder() -> None:
    assert attempt_budget(None) == CONNECTION_ATTEMPTS


def test_a_requested_zero_buys_the_single_try_the_call_already_is() -> None:
    assert attempt_budget(0) == 1


def test_a_negative_request_cannot_buy_fewer_tries_than_one() -> None:
    assert attempt_budget(-3) == 1


def test_a_requested_one_is_honoured_as_given() -> None:
    assert attempt_budget(1) == 1


def test_the_connection_ladder_itself_is_a_reachable_request() -> None:
    assert attempt_budget(CONNECTION_ATTEMPTS) == CONNECTION_ATTEMPTS


def test_a_request_past_the_ladder_is_capped_at_it() -> None:
    assert attempt_budget(CONNECTION_ATTEMPTS + 40) == CONNECTION_ATTEMPTS


def test_a_caller_asking_for_zero_attempts_stops_after_one_open(
    monkeypatch,
) -> None:
    sleeps: list[float] = []
    response, opens = _relay(
        monkeypatch,
        [ConnectionResetError("reset")],
        sleeps,
        max_attempts=0,
    )

    assert opens == 1
    assert sleeps == []
    assert response.success is False


def test_a_caller_asking_past_the_ladder_still_stops_at_it(monkeypatch) -> None:
    sleeps: list[float] = []
    _response, opens = _relay(
        monkeypatch,
        [ConnectionResetError("reset")],
        sleeps,
        max_attempts=CONNECTION_ATTEMPTS + 40,
    )

    assert opens == CONNECTION_ATTEMPTS
    assert len(sleeps) == CONNECTION_ATTEMPTS - 1


def test_an_accepted_envelope_earns_exactly_one_more_try() -> None:
    assert should_retry_response_deadline(0, CONNECTION_ATTEMPTS) is True
    assert (
        should_retry_response_deadline(
            RESPONSE_DEADLINE_ATTEMPTS - 1, CONNECTION_ATTEMPTS
        )
        is False
    )


def test_a_single_attempt_budget_leaves_nothing_for_a_re_attempt() -> None:
    assert should_retry_response_deadline(0, 1) is False


def test_a_server_still_working_is_asked_again_without_backoff(
    monkeypatch,
) -> None:
    sleeps: list[float] = []
    response, opens = _relay(
        monkeypatch,
        [
            ResponseOpenDeadlineError("still working"),
            FakeResponse(envelope(result={"ok": True})),
        ],
        sleeps,
    )

    assert response.success is True
    assert opens == RESPONSE_DEADLINE_ATTEMPTS
    assert sleeps == []


def test_the_response_deadline_never_spends_the_connection_ladder(
    monkeypatch,
) -> None:
    sleeps: list[float] = []
    response, opens = _relay(
        monkeypatch,
        [ResponseOpenDeadlineError("still working")],
        sleeps,
    )

    assert opens == RESPONSE_DEADLINE_ATTEMPTS
    assert opens < https_retry_policy.CONNECTION_ATTEMPTS
    assert sleeps == []
    assert response.success is False
    assert response.error is not None
    assert "exceeded the time limit" in response.error.message


def test_a_one_attempt_caller_never_re_opens_on_a_response_deadline(
    monkeypatch,
) -> None:
    sleeps: list[float] = []
    response, opens = _relay(
        monkeypatch,
        [ResponseOpenDeadlineError("still working")],
        sleeps,
        max_attempts=1,
    )

    assert opens == 1
    assert response.success is False
