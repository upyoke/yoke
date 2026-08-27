"""Atomic per-recipient claims for native wake attempts."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from uuid import uuid4

from yoke_contracts.session_control.wake_instruction import (
    native_wake_instruction_sha256,
)
from yoke_contracts.session_control.wake import EXPLICIT_WAKE_ROUTING_FLAG
from yoke_core.domain.session_relay_evidence import redacted_evidence
from yoke_core.domain.session_relay_storage import marker, shifted
from yoke_core.domain.session_relay_types import WAKE_LEASE_SECONDS, WakeMode
from yoke_core.domain.session_turn_posture import TURN_POSTURES


@dataclass(frozen=True)
class WakeAttemptClaim:
    attempt_id: str
    lease_id: str
    lease_expires_at: str


def _match(column: str, value: Any, placeholder: str) -> tuple[str, tuple[Any, ...]]:
    if value is None:
        return f"{column} IS NULL", ()
    return f"{column}={placeholder}", (value,)


def claim_wake_attempt(
    conn: Any,
    *,
    candidate: Mapping[str, Any],
    now: str,
) -> WakeAttemptClaim | None:
    """CAS one eligible receipt and open its native wake attempt.

    Recipient routing, liveness, posture, and injection facts come from
    eligibility selection. Any newer observation therefore invalidates the
    candidate before a native mutation can start.
    """
    message_id = str(candidate["message_id"])
    session_id = str(candidate["session_id"])
    expected_count = int(candidate.get("wake_attempt_count") or 0)
    expected_last = candidate.get("last_wake_at")
    expected_state = str(candidate.get("state") or "")
    expected_posture = str(candidate.get("turn_posture") or "")
    expected_posture_at = candidate.get("turn_posture_at")
    expected_injection = candidate.get("injection_lease_id")
    escalation = str(candidate.get("wake_escalation") or "")
    try:
        wake_mode = WakeMode(str(candidate.get("wake_mode") or ""))
    except ValueError:
        return None
    if expected_state not in {"pending", "injected"}:
        return None
    if expected_posture not in TURN_POSTURES:
        return None
    # Both refusals below say the same thing: a session that will collect
    # this envelope through its own hooks must not also be resumed underneath
    # it. Two separate things disprove that premise — a caller who asked for
    # this wake outright, and an envelope whose own record shows the hook
    # route stopped running — and either is enough to pass. The CAS still
    # pins the session's activity clock, so a session that ticks before the
    # lease opens takes the delivery back from both of them.
    hooks_will_not_deliver = (
        candidate.get(EXPLICIT_WAKE_ROUTING_FLAG) is True or bool(escalation)
    )
    if candidate.get("liveness") == "active" and not hooks_will_not_deliver:
        return None
    if (
        wake_mode is WakeMode.WAITING
        and not hooks_will_not_deliver
        and (
            expected_state != "pending"
            or expected_posture != "waiting"
            or expected_injection is not None
        )
    ):
        return None
    attempt_id = str(uuid4())
    lease_id = str(uuid4())
    lease_expires_at = shifted(now, seconds=WAKE_LEASE_SECONDS)
    p = marker(conn)
    last_clause = "last_wake_at IS NULL"
    params: list[Any] = [
        now,
        message_id,
        session_id,
        expected_state,
        expected_count,
    ]
    if expected_last is not None:
        last_clause = f"last_wake_at={p}"
        params.append(expected_last)
    posture_at_clause = "hs.turn_posture_at IS NULL"
    posture_params: list[Any] = [expected_posture]
    if expected_posture_at is not None:
        posture_at_clause = f"hs.turn_posture_at={p}"
        posture_params.append(expected_posture_at)
    injection_clause = "injection_lease_id IS NULL"
    injection_params: list[Any] = []
    # An expired lease is a hook that started delivering and died, so it is
    # claimable by every mode that reached this far. Only an unescalated
    # WAITING wake refused one, and it refused above rather than here.
    if expected_injection is not None and (
        wake_mode is WakeMode.IDLE_TIMEOUT or escalation
    ):
        injection_clause = f"injection_lease_id={p} AND injection_lease_expires_at<={p}"
        injection_params.extend((expected_injection, now))
    recipient_clauses: list[str] = []
    recipient_params: list[Any] = []
    for column, key in (
        ("wake_after", "wake_after"),
        ("executor_surface", "executor_surface"),
        ("executor_version", "executor_version"),
        ("machine_id", "machine_id"),
        ("last_injected_at", "last_injected_at"),
    ):
        clause, values = _match(column, candidate.get(key), p)
        recipient_clauses.append(clause)
        recipient_params.extend(values)
    session_clauses: list[str] = []
    session_params: list[Any] = []
    for column, key in (
        ("hs.last_heartbeat", "last_heartbeat"),
        ("hs.last_tool_call_at", "last_tool_call_at"),
        ("hs.ended_at", "ended_at"),
    ):
        clause, values = _match(column, candidate.get(key), p)
        session_clauses.append(clause)
        session_params.extend(values)
    updated = conn.execute(
        "UPDATE session_message_recipients SET wake_attempt_count="
        "wake_attempt_count+1,last_wake_at="
        + p
        + f" WHERE message_id={p} AND session_id={p} AND state={p} "
        + f"AND wake_attempt_count={p} AND {last_clause} "
        + f"AND {injection_clause} AND wake_after<={p} "
        + f"AND {' AND '.join(recipient_clauses)} "
        "AND EXISTS (SELECT 1 FROM harness_sessions hs "
        "WHERE hs.session_id=session_message_recipients.session_id "
        + f"AND hs.turn_posture={p} AND {posture_at_clause} "
        + f"AND {' AND '.join(session_clauses)}"
        + ") "
        "AND NOT EXISTS (SELECT 1 FROM session_message_attempts a "
        "WHERE a.message_id=session_message_recipients.message_id "
        "AND a.target_session_id=session_message_recipients.session_id "
        "AND a.attempt_kind IN ('wake_relay','wake_broker') "
        "AND a.completed_at IS NULL)",
        tuple(
            (
                *params,
                *injection_params,
                now,
                *recipient_params,
                *posture_params,
                *session_params,
            )
        ),
    )
    if updated.rowcount != 1:
        conn.rollback()
        return None
    conn.execute(
        "INSERT INTO session_message_attempts "
        "(attempt_id,message_id,target_session_id,attempt_kind,lease_id,"
        "started_at,evidence) "
        f"VALUES ({','.join(p for _ in range(7))})",
        (
            attempt_id,
            message_id,
            session_id,
            "wake_relay",
            lease_id,
            now,
            redacted_evidence(
                {
                    "native_instruction_sha256": native_wake_instruction_sha256(
                        message_id
                    ),
                    # Why a live-looking session was resumed anyway. Without
                    # it the attempt is indistinguishable from an ordinary
                    # stopped-session wake, and the escalation is precisely
                    # the part an operator needs to be able to question.
                    "wake_escalation": escalation,
                }
            ),
        ),
    )
    return WakeAttemptClaim(
        attempt_id=attempt_id,
        lease_id=lease_id,
        lease_expires_at=lease_expires_at,
    )


__all__ = ["WakeAttemptClaim", "claim_wake_attempt"]
