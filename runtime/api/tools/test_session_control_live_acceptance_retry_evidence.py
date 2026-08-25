"""Retry-aware native wake evidence assertions."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
)
from runtime.api.tools.session_control_live_acceptance_evidence import (
    native_wake_evidence,
)
from yoke_contracts.session_control.wake_instruction import (
    native_wake_instruction_sha256,
)


MESSAGE_ID = "wake-message"


def _attempt(
    attempt_id: str,
    result_code: str,
    *,
    kind: str = "wake_relay",
    broker_session_id: str | None = None,
    completed_at: str | None = "2026-08-25T18:00:01Z",
) -> dict[str, Any]:
    evidence = (
        {"native_instruction_sha256": native_wake_instruction_sha256(MESSAGE_ID)}
        if result_code in {"accepted", "resumed_running", "resumed_completed"}
        else {"reason": "body-free retry outcome"}
    )
    return {
        "attempt_id": attempt_id,
        "target_session_id": "target-session",
        "broker_session_id": broker_session_id,
        "attempt_kind": kind,
        "adapter_revision": "acceptance-adapter-v1",
        "started_at": "2026-08-25T18:00:00Z",
        "completed_at": completed_at,
        "result_code": result_code,
        "evidence": evidence,
    }


def _parse(cell: AcceptanceCell, attempts: list[dict[str, Any]]) -> dict[str, Any]:
    return native_wake_evidence(
        {
            "attempts": attempts,
            "attempt_count": len(attempts),
            "attempts_truncated": False,
        },
        cell=cell,
        session_id="target-session",
        message_id=MESSAGE_ID,
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
            _attempt("attempt-3", "resumed_completed"),
        ],
    )

    assert parsed["result_code"] == "resumed_completed"
    assert parsed["attempt_count"] == 3
    assert parsed["retry_count"] == 2
    assert [item["result_code"] for item in parsed["attempts"]] == [
        "relay_lease_expired",
        "broker_timeout",
        "resumed_completed",
    ]
    assert all("evidence" not in item for item in parsed["attempts"])


def test_resumed_running_success_may_remain_unsettled() -> None:
    cell = AcceptanceCell("claude-cli", "2.1.245", "identify", wake_route="direct")
    parsed = _parse(
        cell,
        [_attempt("attempt-1", "resumed_running", completed_at=None)],
    )
    assert parsed["result_code"] == "resumed_running"
    assert parsed["attempts"][0]["completed_at"] is None


@pytest.mark.parametrize(
    ("attempts", "code"),
    (
        (
            [
                _attempt("attempt-1", "relay_lease_expired", completed_at=None),
                _attempt("attempt-2", "accepted"),
            ],
            "wake_attempt_settlement_invalid",
        ),
        (
            [_attempt("attempt-1", "accepted"), _attempt("attempt-2", "accepted")],
            "wake_attempt_count_invalid",
        ),
        (
            [
                _attempt("attempt-1", "accepted"),
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
        wake_route="broker",
        broker_session_id="broker-session",
    )
    attempts = [
        _attempt("attempt-1", "broker_lost", kind="wake_broker"),
        _attempt(
            "attempt-2",
            "accepted",
            kind="wake_broker",
            broker_session_id="wrong-broker",
        ),
    ]
    with pytest.raises(AcceptanceContractError) as failure:
        _parse(cell, attempts)
    assert failure.value.code == "wake_broker_identity_mismatch"
