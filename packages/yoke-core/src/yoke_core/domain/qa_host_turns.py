"""FIFO host turns owned by durable QA executions, using existing host claims."""

from __future__ import annotations

from yoke_contracts.timestamps import format_instant, iso8601_now, parse_instant
import json
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import query_one, query_rows
from yoke_core.domain.qa_plan_execution_store import canonical, marker
from yoke_core.domain.schema_common import _table_exists

HOST_WAIT_KIND = "qa_host_wait"
HOST_TURN_REASON = "qa-host-turn:"


def host_wait(value: object) -> dict[str, Any] | None:
    try:
        parsed = json.loads(str(value or ""))
    except (TypeError, ValueError):
        return None
    if isinstance(parsed, dict) and parsed.get("kind") == HOST_WAIT_KIND:
        return parsed
    return None


def lock_host_turn(conn: Any, target: Any) -> None:
    """Serialize queue admission and lease release on the physical host."""
    if target.machine_id and db_backend.connection_is_postgres(conn):
        conn.execute(
            "SELECT pg_advisory_xact_lock(hashtextextended(%s, 0))",
            ("qa-host-turn:" + target.machine_id,),
        )


def queued_host_turns(conn: Any, machine: str) -> list[dict[str, Any]]:
    if not _table_exists(conn, "qa_plan_executions"):
        return []
    rows = query_rows(
        conn,
        "SELECT e.id,e.session_id,e.actor_id,e.release_reason,e.execution_order "
        "FROM qa_plan_executions e JOIN harness_sessions s "
        "ON s.session_id=e.session_id "
        "WHERE e.state IN ('waiting','active') AND s.ended_at IS NULL "
        "ORDER BY e.execution_order,e.id",
    )
    queued = []
    for row in rows:
        wait = host_wait(row["release_reason"])
        if wait and wait.get("machine") == machine:
            queued.append({**dict(row), "wait": wait})
    return sorted(
        queued,
        key=lambda row: (
            parse_instant(row["wait"]["queued_at"]),
            row["execution_order"],
        ),
    )


def reservation_for(conn: Any, claim: Any, session_id: str) -> bool:
    """A caller can consume only its own still-live queue reservation."""
    if claim.session_id != session_id:
        return False
    p = marker(conn)
    row = query_one(conn, f"SELECT reason FROM work_claims WHERE id={p}", (claim.id,))
    reason = str(row["reason"] or "") if row else ""
    if not reason.startswith(HOST_TURN_REASON):
        return False
    queued = queued_host_turns(conn, str(claim.target.machine_id))
    match = next(
        (row for row in queued if HOST_TURN_REASON + str(row["id"]) == reason), None
    )
    if match is None:
        return False
    conn.execute(
        f"UPDATE qa_plan_executions SET release_reason=NULL WHERE id={p}",
        (str(match["id"]),),
    )
    return True


def reserve_host_turn(conn: Any, target: Any) -> None:
    """Reserve a free host for the oldest live waiter before outsiders acquire."""
    if not target.machine_id:
        return
    from yoke_core.domain.coordination_claims import active_claim, acquire

    if active_claim(conn, target) is not None:
        return
    queued = queued_host_turns(conn, target.machine_id)
    if not queued:
        return
    first = queued[0]
    claim = acquire(
        conn,
        target,
        str(first["session_id"]),
        reason=HOST_TURN_REASON + str(first["id"]),
        commit=False,
    )
    from yoke_contracts.session_control.models import RecipientSelector
    from yoke_core.domain.session_explicit_wake import mark_explicit_stopped_wake
    from yoke_core.domain.session_message_service import send_message

    created = send_message(
        conn,
        actor_id=int(first["actor_id"]),
        sender_session_id=None,
        selector=RecipientSelector(session_ids=[str(first["session_id"])]),
        body=(
            f"QA host turn ready: {target.machine_id}; reserved lease {claim.id}. "
            f"Resume with: {first['wait']['resume_command']}. "
            "The requirement is still open; restore its declared starting state before walking."
        ),
        idempotency_key=f"qa-host-turn:{first['id']}:{claim.id}",
        idempotency_intent_only=True,
        commit=False,
    )
    mark_explicit_stopped_wake(
        conn,
        message_id=str(created["message_id"]),
        session_id=str(first["session_id"]),
    )


def record_host_wait(
    conn: Any,
    execution: dict[str, Any],
    *,
    machine: str,
    rationale: str,
    commit: bool = True,
) -> dict:
    """Keep the cursor open, release owned hosts and durably queue one host turn."""
    from yoke_core.domain.machine_qa_capability import host_claim_target
    from yoke_core.domain.qa_plan_execution_continuation import continuation_recipe
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution

    target = host_claim_target(machine)
    previous = host_wait(execution.get("release_reason"))
    targets = [target]
    if previous and previous["machine"] != machine:
        targets.append(host_claim_target(previous["machine"]))
    for candidate in sorted(targets, key=lambda value: str(value.machine_id)):
        lock_host_turn(conn, candidate)
    if previous and previous["machine"] != machine:
        release_host_reservations(conn, str(execution["id"]))
    wait = {
        "kind": HOST_WAIT_KIND,
        "machine": machine,
        "rationale": rationale,
        "queued_at": (
            format_instant(parse_instant(previous["queued_at"]))
            if previous and previous["machine"] == machine
            else iso8601_now()
        ),
        "resume_command": continuation_recipe(conn, execution).removesuffix(
            " --continue-mission"
        ),
    }
    # Store before releasing: release atomically grants the next FIFO turn.
    p = marker(conn)
    conn.execute(
        f"UPDATE qa_plan_executions SET release_reason={p} WHERE id={p}",
        (canonical(wait), str(execution["id"])),
    )
    execution["release_reason"] = canonical(wait)
    finish_plan_execution(
        conn, execution, state="waiting", reason=canonical(wait), commit=False
    )
    reserve_host_turn(conn, target)
    if commit:
        conn.commit()
    return {
        "state": "waiting",
        "execution_id": str(execution["id"]),
        "cursor_ordinal": int(execution["cursor_ordinal"]),
        "host_wait": wait,
    }


def release_host_reservations(conn: Any, execution_id: str) -> None:
    """Cancel an unconsumed turn when its owning execution settles."""
    from yoke_core.domain.coordination_claims import release

    p = marker(conn)
    conn.execute(
        f"UPDATE qa_plan_executions SET release_reason=NULL WHERE id={p}",
        (execution_id,),
    )
    if not _table_exists(conn, "work_claims"):
        return
    rows = query_rows(
        conn,
        f"SELECT id FROM work_claims WHERE reason={p} AND released_at IS NULL",
        (HOST_TURN_REASON + execution_id,),
    )
    for row in rows:
        release(conn, int(row["id"]), "qa-host-wait-cancelled", commit=False)
