"""Fail-closed parsers for body-free Fleet acceptance evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
)
from yoke_contracts.session_control.wake_instruction import (
    native_wake_instruction_sha256,
)


_ATTEMPT_KEYS = frozenset(
    {
        "adapter_revision",
        "attempt_id",
        "attempt_kind",
        "broker_session_id",
        "completed_at",
        "evidence",
        "result_code",
        "started_at",
        "target_session_id",
    }
)


def one_recipient(
    value: Any,
    *,
    session_id: str,
    surface: str,
) -> dict[str, Any]:
    if not isinstance(value, list) or len(value) != 1 or not isinstance(value[0], dict):
        raise AcceptanceContractError("recipient_evidence_invalid", surface=surface)
    recipient = value[0]
    if recipient.get("session_id") != session_id:
        raise AcceptanceContractError("recipient_identity_mismatch", surface=surface)
    return recipient


def receipt_count(value: Any, *, surface: str) -> int:
    if isinstance(value, bool):
        raise AcceptanceContractError("receipt_count_invalid", surface=surface)
    try:
        count = int(value or 0)
    except (TypeError, ValueError) as exc:
        raise AcceptanceContractError("receipt_count_invalid", surface=surface) from exc
    if count < 0:
        raise AcceptanceContractError("receipt_count_invalid", surface=surface)
    return count


def native_wake_evidence(
    value: Any,
    *,
    cell: AcceptanceCell,
    session_id: str,
    message_id: str,
) -> dict[str, Any]:
    if not isinstance(value, dict) or value.get("attempts_truncated") is not False:
        raise AcceptanceContractError(
            "attempt_evidence_incomplete", surface=cell.surface
        )
    attempts = value.get("attempts")
    if not isinstance(attempts, list) or any(
        not isinstance(attempt, dict) or set(attempt) != _ATTEMPT_KEYS
        for attempt in attempts
    ):
        raise AcceptanceContractError("attempt_evidence_invalid", surface=cell.surface)
    total = receipt_count(value.get("attempt_count"), surface=cell.surface)
    if total != len(attempts):
        raise AcceptanceContractError(
            "attempt_evidence_incomplete", surface=cell.surface
        )
    wake_attempts = [
        attempt
        for attempt in attempts
        if attempt.get("attempt_kind") in {"wake_relay", "wake_broker"}
    ]
    if cell.route == "none":
        if wake_attempts:
            raise AcceptanceContractError(
                "unsupported_native_wake_present", surface=cell.surface
            )
        return {
            "route": "none",
            "attempt_count": 0,
            "attempt_deduplicated": True,
            "native_traffic_body_free": True,
        }
    if len(wake_attempts) != 1:
        raise AcceptanceContractError(
            "wake_attempt_count_invalid", surface=cell.surface
        )
    attempt = wake_attempts[0]
    expected_kind = "wake_broker" if cell.route == "broker" else "wake_relay"
    if attempt.get("attempt_kind") != expected_kind:
        raise AcceptanceContractError("wake_route_mismatch", surface=cell.surface)
    if attempt.get("target_session_id") != session_id:
        raise AcceptanceContractError(
            "wake_target_identity_mismatch", surface=cell.surface
        )
    expected_broker = cell.broker_session_id if cell.route == "broker" else None
    if attempt.get("broker_session_id") != expected_broker:
        raise AcceptanceContractError(
            "wake_broker_identity_mismatch", surface=cell.surface
        )
    required = (
        attempt.get("attempt_id"),
        attempt.get("started_at"),
        attempt.get("completed_at"),
        attempt.get("adapter_revision"),
    )
    if not all(isinstance(item, str) and item.strip() for item in required):
        raise AcceptanceContractError(
            "wake_attempt_settlement_invalid", surface=cell.surface
        )
    if attempt.get("result_code") != "accepted":
        raise AcceptanceContractError("wake_attempt_not_accepted", surface=cell.surface)
    evidence = attempt.get("evidence")
    digest = native_wake_instruction_sha256(message_id)
    if (
        not isinstance(evidence, dict)
        or evidence.get("native_instruction_sha256") != digest
    ):
        raise AcceptanceContractError(
            "native_instruction_evidence_missing", surface=cell.surface
        )
    return {
        "route": cell.route,
        "attempt_id": attempt["attempt_id"],
        "attempt_kind": expected_kind,
        "broker_session_id": expected_broker,
        "result_code": "accepted",
        "adapter_revision": attempt["adapter_revision"],
        "native_instruction_sha256": digest,
        "attempt_count": 1,
        "attempt_deduplicated": True,
        "native_traffic_body_free": True,
    }


def wait_for_ack(
    receipt: Callable[[AcceptanceCell, str, str], dict[str, Any]],
    *,
    cell: AcceptanceCell,
    session_id: str,
    message_id: str,
    timeout: float,
    poll: float,
    sleep: Callable[[float], None],
    monotonic: Callable[[], float],
    require_wake: bool = False,
) -> dict[str, Any]:
    deadline = monotonic() + timeout
    while True:
        observed = receipt(cell, session_id, message_id)
        if observed["state"] == "acknowledged":
            if observed["injection_count"] < 1 or not observed["acknowledged_at"]:
                raise AcceptanceContractError(
                    "ack_evidence_invalid", surface=cell.surface
                )
            if require_wake and (
                observed["wake_attempt_count"] < 1 or not observed["last_wake_at"]
            ):
                raise AcceptanceContractError(
                    "wake_evidence_missing", surface=cell.surface
                )
            if require_wake:
                observed["native_wake"] = native_wake_evidence(
                    observed.pop("attempt_evidence"),
                    cell=cell,
                    session_id=session_id,
                    message_id=message_id,
                )
            else:
                observed.pop("attempt_evidence")
            return observed
        if observed["state"] in {"expired", "cancelled"}:
            raise AcceptanceContractError(
                "receipt_terminal_without_ack", surface=cell.surface
            )
        if monotonic() >= deadline:
            raise AcceptanceContractError("ack_timeout", surface=cell.surface)
        sleep(poll)


__all__ = [
    "native_wake_evidence",
    "one_recipient",
    "receipt_count",
    "wait_for_ack",
]
