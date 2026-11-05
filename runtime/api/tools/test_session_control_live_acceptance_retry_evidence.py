"""Retry-aware native wake evidence assertions."""

from __future__ import annotations

from runtime.api.tools.session_control_live_acceptance_retry_evidence_test_support import (
    MESSAGE_ID as MESSAGE_ID,
    _acknowledged as _acknowledged,
    _attempt as _attempt,
    _parse as _parse,
)


from typing import Any

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
)
from runtime.api.tools.session_control_live_acceptance_evidence import (
    wait_for_ack,
)
from runtime.api.tools.session_control_live_acceptance_clock_test_support import (
    AcceptanceClock,
)
from runtime.api.tools.session_control_live_acceptance_wake_route import (
    MACHINE_SELECTED_ROUTE,
)
from yoke_contracts.session_control.wake_delivery import (
    WAKE_DELIVERED_RESULT,
)


def test_settled_retries_before_one_success_are_retained_body_free() -> None:
    cell = AcceptanceCell(
        "claude-desktop", "1.34493.1", "identify", wake_route="direct"
    )
    parsed = _parse(
        cell,
        [
            _attempt("attempt-1", "relay_lease_expired"),
            _attempt("attempt-2", "broker_timeout", kind="wake_broker"),
            _attempt("attempt-3", WAKE_DELIVERED_RESULT),
        ],
    )

    assert parsed["result_code"] == WAKE_DELIVERED_RESULT
    assert parsed["attempt_count"] == 3
    assert parsed["retry_count"] == 2
    assert [item["result_code"] for item in parsed["attempts"]] == [
        "relay_lease_expired",
        "broker_timeout",
        WAKE_DELIVERED_RESULT,
    ]
    assert all("evidence" not in item for item in parsed["attempts"])


def test_resumed_running_shape_is_valid_while_in_flight() -> None:
    cell = AcceptanceCell("claude-cli", "2.1.245", "identify", wake_route="direct")
    parsed = _parse(
        cell,
        [_attempt("attempt-1", "resumed_running", completed_at=None)],
    )
    assert parsed["result_code"] == "resumed_running"
    assert parsed["attempts"][0]["completed_at"] is None


def test_ack_waits_for_the_delivery_verdict_to_settle() -> None:
    cell = AcceptanceCell("claude-cli", "2.1.245", "identify", wake_route="direct")
    receipts = iter(
        (
            _acknowledged(_attempt("attempt-1", "resumed_running", completed_at=None)),
            _acknowledged(_attempt("attempt-1", WAKE_DELIVERED_RESULT)),
        )
    )
    clock = AcceptanceClock()

    observed = wait_for_ack(
        lambda *_args: next(receipts),
        cell=cell,
        session_id="target-session",
        message_id=MESSAGE_ID,
        timeout=2,
        poll=1,
        sleep=clock.sleep,
        monotonic=clock.monotonic,
        expected_route="direct",
        require_wake=True,
    )

    assert observed["native_wake"]["result_code"] == WAKE_DELIVERED_RESULT
    assert observed["native_wake"]["attempts"][0]["completed_at"]
    assert clock.value == 1


def test_ack_reports_a_named_timeout_when_resume_never_settles() -> None:
    cell = AcceptanceCell("claude-cli", "2.1.245", "identify", wake_route="direct")
    clock = AcceptanceClock()

    with pytest.raises(AcceptanceContractError) as failure:
        wait_for_ack(
            lambda *_args: _acknowledged(
                _attempt("attempt-1", "resumed_running", completed_at=None)
            ),
            cell=cell,
            session_id="target-session",
            message_id=MESSAGE_ID,
            timeout=1,
            poll=1,
            sleep=clock.sleep,
            monotonic=clock.monotonic,
            expected_route="direct",
            require_wake=True,
        )

    assert failure.value.code == "wake_attempt_settlement_timeout"
    attempts = failure.value.evidence["native_wake_attempts"]["attempts"]
    assert attempts[0]["result_code"] == "resumed_running"
    assert attempts[0]["completed_at"] is None


@pytest.mark.parametrize(
    ("attempts", "code"),
    (
        (
            [
                _attempt("attempt-1", "relay_lease_expired", completed_at=None),
                _attempt("attempt-2", WAKE_DELIVERED_RESULT),
            ],
            "wake_attempt_settlement_invalid",
        ),
        (
            [
                _attempt("attempt-1", WAKE_DELIVERED_RESULT),
                _attempt("attempt-2", WAKE_DELIVERED_RESULT),
            ],
            "wake_attempt_count_invalid",
        ),
        (
            [
                _attempt("attempt-1", WAKE_DELIVERED_RESULT),
                _attempt("attempt-2", "relay_lease_expired"),
            ],
            "wake_attempt_order_invalid",
        ),
    ),
)
def test_retry_evidence_fails_closed(attempts: list[dict[str, Any]], code: str) -> None:
    cell = AcceptanceCell("claude-cli", "2.1.245", "identify", wake_route="direct")
    with pytest.raises(AcceptanceContractError) as failure:
        _parse(cell, attempts)
    assert failure.value.code == code


def test_broker_success_still_requires_the_exact_peer() -> None:
    cell = AcceptanceCell(
        "codex-cli",
        "0.149.0-alpha.4",
        "identify",
        acceptance_role="broker",
        wake_route=MACHINE_SELECTED_ROUTE,
        broker_session_id="broker-session",
    )
    attempts = [
        _attempt("attempt-1", "broker_lost", kind="wake_broker"),
        _attempt(
            "attempt-2",
            WAKE_DELIVERED_RESULT,
            kind="wake_broker",
            broker_session_id="wrong-broker",
        ),
    ]
    with pytest.raises(AcceptanceContractError) as failure:
        _parse(cell, attempts, expected_route="broker")
    assert failure.value.code == "wake_broker_identity_mismatch"
