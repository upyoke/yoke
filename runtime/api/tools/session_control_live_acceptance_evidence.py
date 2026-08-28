"""Fail-closed parsers for body-free Fleet acceptance evidence."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from runtime.api.tools.session_control_live_acceptance_contract import (
    AcceptanceCell,
    AcceptanceContractError,
)
from yoke_contracts.session_control.wake_delivery import (
    WAKE_ATTEMPT_SUCCESS_RESULTS,
    wake_attempt_unsettled,
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
_SKIP_RESULTS = frozenset({"skipped_surface", "skipped_version", "skipped_operation"})
_WAKE_KINDS = frozenset({"wake_relay", "wake_broker"})


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


def _attempt_summary(attempt: dict[str, Any]) -> dict[str, Any]:
    keys = (
        "attempt_id",
        "attempt_kind",
        "result_code",
        "started_at",
        "completed_at",
    )
    return {
        key: value if isinstance((value := attempt.get(key)), str) else None
        for key in keys
    }


def _require_attempt_metadata(
    attempt: dict[str, Any],
    *,
    surface: str,
    completed_required: bool,
) -> None:
    required = (
        attempt.get("attempt_id"),
        attempt.get("started_at"),
        attempt.get("adapter_revision"),
        attempt.get("result_code"),
    )
    if not all(isinstance(item, str) and item.strip() for item in required):
        raise AcceptanceContractError(
            "wake_attempt_settlement_invalid", surface=surface
        )
    completed = attempt.get("completed_at")
    if completed_required and not (isinstance(completed, str) and completed.strip()):
        raise AcceptanceContractError(
            "wake_attempt_settlement_invalid", surface=surface
        )


def _unsupported_wake_evidence(
    wake_attempts: list[dict[str, Any]],
    *,
    cell: AcceptanceCell,
    session_id: str,
) -> dict[str, Any]:
    if len(wake_attempts) != 1:
        raise AcceptanceContractError(
            "unsupported_wake_attempt_count_invalid", surface=cell.surface
        )
    attempt = wake_attempts[0]
    _require_attempt_metadata(attempt, surface=cell.surface, completed_required=True)
    if (
        attempt.get("attempt_kind") != "wake_relay"
        or attempt.get("target_session_id") != session_id
        or attempt.get("broker_session_id") is not None
        or attempt.get("result_code") not in _SKIP_RESULTS
    ):
        raise AcceptanceContractError(
            "unsupported_native_wake_present", surface=cell.surface
        )
    return {
        "route": "none",
        "result_code": attempt["result_code"],
        "attempt_count": 1,
        "retry_count": 0,
        "attempts": [_attempt_summary(attempt)],
        "attempt_deduplicated": True,
        "native_traffic_body_free": True,
    }


def native_wake_evidence(
    value: Any,
    *,
    cell: AcceptanceCell,
    session_id: str,
    message_id: str,
    expected_route: str,
) -> dict[str, Any]:
    """Check one settled wake against the route the caller resolved for it.

    The expectation is an argument rather than a cell field because a
    broker-capable cell's route is chosen by the plane from live machine
    state; only an unsupported cell's route is knowable from the matrix.
    """
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
        attempt for attempt in attempts if attempt.get("attempt_kind") in _WAKE_KINDS
    ]
    if expected_route == "none":
        return _unsupported_wake_evidence(
            wake_attempts, cell=cell, session_id=session_id
        )
    successes = [
        index
        for index, attempt in enumerate(wake_attempts)
        if attempt.get("result_code") in WAKE_ATTEMPT_SUCCESS_RESULTS
    ]
    if not successes:
        raise AcceptanceContractError("wake_attempt_not_accepted", surface=cell.surface)
    if len(successes) != 1:
        raise AcceptanceContractError(
            "wake_attempt_count_invalid", surface=cell.surface
        )
    selected_index = successes[0]
    if selected_index != len(wake_attempts) - 1:
        raise AcceptanceContractError(
            "wake_attempt_order_invalid", surface=cell.surface
        )
    for retry in wake_attempts[:selected_index]:
        _require_attempt_metadata(retry, surface=cell.surface, completed_required=True)
    attempt = wake_attempts[selected_index]
    expected_kind = "wake_broker" if expected_route == "broker" else "wake_relay"
    if attempt.get("attempt_kind") != expected_kind:
        raise AcceptanceContractError("wake_route_mismatch", surface=cell.surface)
    if attempt.get("target_session_id") != session_id:
        raise AcceptanceContractError(
            "wake_target_identity_mismatch", surface=cell.surface
        )
    expected_broker = cell.broker_session_id if expected_route == "broker" else None
    if attempt.get("broker_session_id") != expected_broker:
        raise AcceptanceContractError(
            "wake_broker_identity_mismatch", surface=cell.surface
        )
    result_code = str(attempt["result_code"])
    _require_attempt_metadata(
        attempt,
        surface=cell.surface,
        completed_required=not wake_attempt_unsettled(result_code),
    )
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
        "route": expected_route,
        "attempt_id": attempt["attempt_id"],
        "attempt_kind": expected_kind,
        "broker_session_id": expected_broker,
        "result_code": result_code,
        "adapter_revision": attempt["adapter_revision"],
        "native_instruction_sha256": digest,
        "attempt_count": len(wake_attempts),
        "retry_count": selected_index,
        "attempts": [_attempt_summary(item) for item in wake_attempts],
        "attempt_deduplicated": True,
        "native_traffic_body_free": True,
    }


def _body_free_receipt_evidence(observed: dict[str, Any]) -> dict[str, Any]:
    evidence = {
        key: observed.get(key)
        for key in (
            "message_id",
            "state",
            "injection_count",
            "wake_attempt_count",
            "acknowledged_at",
            "last_wake_at",
        )
    }
    raw_attempts = observed.get("attempt_evidence")
    if isinstance(raw_attempts, dict):
        attempts = raw_attempts.get("attempts")
        evidence["native_wake_attempts"] = {
            "attempt_count": raw_attempts.get("attempt_count"),
            "attempts_truncated": raw_attempts.get("attempts_truncated"),
            "attempts": [
                _attempt_summary(attempt)
                for attempt in attempts
                if isinstance(attempt, dict)
            ]
            if isinstance(attempts, list)
            else [],
        }
    evidence["native_traffic_body_free"] = True
    return evidence


def _receipt_failure(
    code: str, *, cell: AcceptanceCell, observed: dict[str, Any]
) -> AcceptanceContractError:
    return AcceptanceContractError(
        code,
        surface=cell.surface,
        evidence=_body_free_receipt_evidence(observed),
    )


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
    expected_route: str,
    require_wake: bool = False,
    minimum_injections: int = 1,
) -> dict[str, Any]:
    deadline = monotonic() + timeout
    while True:
        observed = receipt(cell, session_id, message_id)
        if observed["state"] == "acknowledged":
            if (
                observed["injection_count"] < minimum_injections
                or not observed["acknowledged_at"]
            ):
                raise _receipt_failure(
                    "ack_evidence_invalid", cell=cell, observed=observed
                )
            if require_wake and (
                observed["wake_attempt_count"] < 1 or not observed["last_wake_at"]
            ):
                raise _receipt_failure(
                    "wake_evidence_missing", cell=cell, observed=observed
                )
            if require_wake:
                try:
                    observed["native_wake"] = native_wake_evidence(
                        observed["attempt_evidence"],
                        cell=cell,
                        session_id=session_id,
                        message_id=message_id,
                        expected_route=expected_route,
                    )
                except AcceptanceContractError as exc:
                    raise _receipt_failure(
                        exc.code, cell=cell, observed=observed
                    ) from exc
                if (
                    observed["wake_attempt_count"]
                    != observed["native_wake"]["attempt_count"]
                ):
                    raise _receipt_failure(
                        "wake_attempt_count_mismatch", cell=cell, observed=observed
                    )
                if wake_attempt_unsettled(observed["native_wake"]["result_code"]):
                    if monotonic() >= deadline:
                        raise _receipt_failure(
                            "wake_attempt_settlement_timeout",
                            cell=cell,
                            observed=observed,
                        )
                    sleep(poll)
                    continue
                observed.pop("attempt_evidence")
            else:
                observed.pop("attempt_evidence")
            return observed
        if observed["state"] in {"expired", "cancelled"}:
            raise _receipt_failure(
                "receipt_terminal_without_ack", cell=cell, observed=observed
            )
        if monotonic() >= deadline:
            raise _receipt_failure("ack_timeout", cell=cell, observed=observed)
        sleep(poll)


__all__ = [
    "native_wake_evidence",
    "one_recipient",
    "receipt_count",
    "wait_for_ack",
]
