# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from typing import Any

import pytest

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
)

from runtime.api.tools.session_control_live_acceptance_evidence import (
    native_wake_evidence,
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
    WAKE_DELIVERY_UNVERIFIED_RESULTS,
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
        if result_code in {WAKE_DELIVERED_RESULT, *WAKE_DELIVERY_UNVERIFIED_RESULTS}
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


def _parse(
    cell: AcceptanceCell,
    attempts: list[dict[str, Any]],
    *,
    expected_route: str = "direct",
) -> dict[str, Any]:
    return native_wake_evidence(
        {
            "attempts": attempts,
            "attempt_count": len(attempts),
            "attempts_truncated": False,
        },
        cell=cell,
        session_id="target-session",
        message_id=MESSAGE_ID,
        expected_route=expected_route,
    )


def _acknowledged(attempt: dict[str, Any]) -> dict[str, Any]:
    return {
        "message_id": MESSAGE_ID,
        "state": "acknowledged",
        "injection_count": 1,
        "wake_attempt_count": 1,
        "acknowledged_at": "2026-08-25T18:00:02Z",
        "last_wake_at": "2026-08-25T18:00:00Z",
        "attempt_evidence": {
            "attempts": [attempt],
            "attempt_count": 1,
            "attempts_truncated": False,
        },
    }
