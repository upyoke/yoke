"""One-hop wake reservations delivered through a live same-machine peer."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Mapping
from uuid import uuid4

from yoke_contracts.session_control.capabilities import capability_for_surface
from yoke_contracts.session_control.wake_delivery import (
    TURN_WITHOUT_INJECTION_RESULT,
)
from yoke_core.domain import db_backend
from yoke_core.domain.session_broker_wake_recruit import (
    machine_has_fresh_relay,
    should_defer_operator_facing_broker,
)
from yoke_core.domain.session_message_authorization import project_policy
from yoke_core.domain.session_message_types import (
    parse_timestamp,
    row_dict,
    timestamp,
    utc_now,
)
from yoke_core.domain.session_message_wake import wake_eligible_recipients
from yoke_core.domain.session_relay_evidence import redacted_evidence
from yoke_core.domain.session_relay_storage import (
    marker,
)


BROKER_HOOK_LEASE_SECONDS = 30
BROKER_JOB_TIMEOUT_SECONDS = 300
BROKER_ADAPTER_REVISION = "session-broker-hook-v1"
BROKER_COMMAND = "yoke relay serve-once --broker"
DIRECT_FALLBACK_RESULTS = frozenset(
    {
        "failed",
        # A native resume that delivered nothing has proved the direct route
        # cannot reach this turn. The peer-hook broker is the other route.
        TURN_WITHOUT_INJECTION_RESULT,
        "not_found",
        "outcome_unknown",
        "relay_lease_expired",
        "unsupported_surface",
        "version_mismatch",
    }
)


@dataclass(frozen=True)
class BrokerWakeLease:
    attempt_id: str
    lease_id: str
    message_id: str
    command: str


def _lock(conn: Any, alias: str) -> str:
    if db_backend.connection_is_postgres(conn):
        return f" FOR UPDATE OF {alias}"
    return ""


def _begin(conn: Any) -> None:
    if not db_backend.connection_is_postgres(conn) and not bool(
        getattr(conn, "in_transaction", False)
    ):
        conn.execute("BEGIN IMMEDIATE")


def _latest_wake_result(
    conn: Any, *, message_id: str, session_id: str
) -> tuple[str, str, str] | None:
    p = marker(conn)
    row = conn.execute(
        "SELECT attempt_kind,result_code,completed_at FROM session_message_attempts "
        f"WHERE message_id={p} AND target_session_id={p} "
        "AND attempt_kind IN ('wake_relay','wake_broker') "
        "AND completed_at IS NOT NULL ORDER BY started_at DESC,attempt_id DESC LIMIT 1",
        (message_id, session_id),
    ).fetchone()
    return (
        (str(row[0]), str(row[1] or ""), str(row[2] or "")) if row is not None else None
    )


def direct_wake_waits_for_broker(
    conn: Any,
    *,
    message_id: str,
    session_id: str,
    now: datetime | str | None = None,
) -> bool:
    """Keep a failed direct route from immediately claiming itself again."""
    latest = _latest_wake_result(conn, message_id=message_id, session_id=session_id)
    if not latest or latest[0] != "wake_relay":
        return False
    completed = parse_timestamp(latest[2])
    current = parse_timestamp(now) if isinstance(now, str) else now
    return bool(
        latest[1] in DIRECT_FALLBACK_RESULTS
        and completed
        and (current or utc_now())
        < completed + timedelta(seconds=BROKER_JOB_TIMEOUT_SECONDS)
    )


def _broker_session(conn: Any, session_id: str) -> Mapping[str, Any] | None:
    p = marker(conn)
    row = conn.execute(
        "SELECT session_id,machine_id,executor_surface,ended_at "
        "FROM harness_sessions "
        f"WHERE session_id={p}",
        (session_id,),
    ).fetchone()
    return row_dict(row) if row is not None else None


def _hook_can_broker(row: Mapping[str, Any], hook_event: str) -> bool:
    if row.get("ended_at") is not None or hook_event in {"Stop", "SessionEnd"}:
        return False
    capability = capability_for_surface(str(row.get("executor_surface") or ""))
    return bool(capability and hook_event in capability.inject_events)


def _open_broker_role(conn: Any, session_id: str) -> bool:
    p = marker(conn)
    return (
        conn.execute(
            "SELECT 1 FROM session_message_attempts "
            "WHERE attempt_kind='wake_broker' AND completed_at IS NULL "
            f"AND (broker_session_id={p} OR target_session_id={p}) LIMIT 1",
            (session_id, session_id),
        ).fetchone()
        is not None
    )


def _candidate_routes(
    conn: Any, *, broker_session_id: str, now: datetime
) -> list[dict[str, Any]]:
    broker = _broker_session(conn, broker_session_id)
    if broker is None or not broker.get("machine_id"):
        return []
    candidates = wake_eligible_recipients(
        conn, now=now, bypass_waiting_retry_cooldown=True
    )
    eligible: list[dict[str, Any]] = []
    for row in candidates:
        if row.get("machine_id") != broker.get("machine_id"):
            continue
        if str(row["session_id"]) == broker_session_id:
            continue
        direct_failed = direct_wake_waits_for_broker(
            conn,
            message_id=str(row["message_id"]),
            session_id=str(row["session_id"]),
            now=now,
        )
        policy = project_policy(conn, int(row["project_id"]))
        previous = parse_timestamp(row.get("last_wake_at"))
        waiting_cooldown = (
            row.get("wake_mode") == "waiting"
            and int(row.get("wake_attempt_count") or 0) > 0
            and (
                previous is None
                or previous + timedelta(seconds=policy.wake_after_idle_seconds) > now
            )
        )
        if waiting_cooldown and not direct_failed:
            continue
        eligible.append(row)
    return eligible


def _same(value: Any, expected: Any) -> bool:
    return str(value or "") == str(expected or "")


def _reserve_candidate(
    conn: Any,
    *,
    broker_session_id: str,
    candidate: Mapping[str, Any],
    now: str,
) -> BrokerWakeLease | None:
    p = marker(conn)
    _begin(conn)
    try:
        broker = conn.execute(
            "SELECT machine_id,executor_surface,ended_at FROM harness_sessions hs "
            f"WHERE session_id={p}" + _lock(conn, "hs"),
            (broker_session_id,),
        ).fetchone()
        target = conn.execute(
            "SELECT r.state,r.wake_attempt_count,r.last_wake_at,"
            "r.injection_lease_id,hs.machine_id,hs.turn_posture,hs.turn_posture_at,"
            "hs.last_heartbeat,hs.last_tool_call_at,hs.ended_at,r.wake_after,"
            "r.executor_surface,r.executor_version "
            "FROM session_message_recipients r JOIN session_messages m "
            "ON m.message_id=r.message_id JOIN harness_sessions hs "
            "ON hs.session_id=r.session_id "
            f"WHERE r.message_id={p} AND r.session_id={p} "
            f"AND m.cancelled_at IS NULL AND m.expires_at>{p}" + _lock(conn, "r"),
            (candidate["message_id"], candidate["session_id"], now),
        ).fetchone()
        if broker is None or target is None:
            conn.rollback()
            return None
        if str(candidate["session_id"]) == broker_session_id:
            conn.rollback()
            return None
        checks = (
            _same(broker[0], candidate.get("machine_id")),
            broker[2] is None,
            _same(target[0], candidate.get("state")),
            int(target[1] or 0) == int(candidate.get("wake_attempt_count") or 0),
            _same(target[2], candidate.get("last_wake_at")),
            _same(target[3], candidate.get("injection_lease_id")),
            _same(target[4], candidate.get("machine_id")),
            _same(target[5], candidate.get("turn_posture")),
            _same(target[6], candidate.get("turn_posture_at")),
            _same(target[7], candidate.get("last_heartbeat")),
            _same(target[8], candidate.get("last_tool_call_at")),
            _same(target[9], candidate.get("ended_at")),
            _same(target[10], candidate.get("wake_after")),
            _same(target[11], candidate.get("executor_surface")),
            _same(target[12], candidate.get("executor_version")),
        )
        if not all(checks) or _open_broker_role(conn, broker_session_id):
            conn.rollback()
            return None
        open_attempt = conn.execute(
            "SELECT 1 FROM session_message_attempts "
            f"WHERE message_id={p} AND target_session_id={p} "
            "AND attempt_kind IN ('wake_relay','wake_broker') "
            "AND completed_at IS NULL LIMIT 1",
            (candidate["message_id"], candidate["session_id"]),
        ).fetchone()
        if open_attempt is not None:
            conn.rollback()
            return None
        attempt_id = str(uuid4())
        lease_id = str(uuid4())
        escalation = str(candidate.get("wake_escalation") or "")
        conn.execute(
            "UPDATE session_message_recipients SET wake_attempt_count="
            "wake_attempt_count+1,wake_escalation="
            + p
            + ",last_wake_at="
            + p
            + f" WHERE message_id={p} AND session_id={p}",
            (escalation or None, now, candidate["message_id"], candidate["session_id"]),
        )
        conn.execute(
            "INSERT INTO session_message_attempts "
            "(attempt_id,message_id,target_session_id,broker_session_id,"
            "attempt_kind,adapter_revision,lease_id,started_at,result_code,evidence) "
            f"VALUES ({','.join(p for _ in range(10))})",
            (
                attempt_id,
                candidate["message_id"],
                candidate["session_id"],
                broker_session_id,
                "wake_broker",
                BROKER_ADAPTER_REVISION,
                lease_id,
                now,
                "broker_hook_leased",
                redacted_evidence(
                    {
                        "result_code": "broker_hook_leased",
                        # Carried from eligibility so a broker-routed resume
                        # of a live-looking session says why, exactly as the
                        # direct route's attempt does.
                        "wake_escalation": escalation,
                    }
                ),
            ),
        )
        conn.commit()
        return BrokerWakeLease(
            attempt_id=attempt_id,
            lease_id=lease_id,
            message_id=str(candidate["message_id"]),
            command=f"{BROKER_COMMAND} --broker-lease {lease_id}",
        )
    except Exception:
        conn.rollback()
        raise


def lease_broker_wake_for_hook(
    conn: Any,
    *,
    broker_session_id: str,
    hook_event: str,
    now: datetime | None = None,
) -> BrokerWakeLease | None:
    """Reserve one direct-fallback wake for the peer whose hook is running."""
    from yoke_core.domain.session_broker_wake_settlement import (
        settle_broker_wake_losses,
    )

    current = now or utc_now()
    settle_broker_wake_losses(conn, now=current)
    broker = _broker_session(conn, broker_session_id)
    if broker is None or not _hook_can_broker(broker, hook_event):
        return None
    if _open_broker_role(conn, broker_session_id):
        return None
    stamp = timestamp(current)
    if machine_has_fresh_relay(conn, str(broker.get("machine_id") or ""), stamp):
        return None
    candidates = _candidate_routes(
        conn, broker_session_id=broker_session_id, now=current
    )
    if should_defer_operator_facing_broker(
        conn,
        broker=broker,
        exclude_session_ids={str(row["session_id"]) for row in candidates},
    ):
        return None
    for candidate in candidates:
        lease = _reserve_candidate(
            conn,
            broker_session_id=broker_session_id,
            candidate=candidate,
            now=stamp,
        )
        if lease is not None:
            return lease
    return None


__all__ = [
    "BROKER_ADAPTER_REVISION",
    "BROKER_COMMAND",
    "BROKER_HOOK_LEASE_SECONDS",
    "BROKER_JOB_TIMEOUT_SECONDS",
    "BrokerWakeLease",
    "DIRECT_FALLBACK_RESULTS",
    "direct_wake_waits_for_broker",
    "lease_broker_wake_for_hook",
]
