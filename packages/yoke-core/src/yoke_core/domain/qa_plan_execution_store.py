"""Persistence helpers for durable ordered QA plan executions."""

from __future__ import annotations

import hashlib
import json
from typing import Any, Mapping

from yoke_core.domain import db_backend
from yoke_core.domain.db_helpers import iso8601_now


class QaPlanExecutionStateError(ValueError):
    """A durable ordered-plan execution transition is invalid."""


def marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def canonical(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def roster_digest(roster: list[dict[str, Any]]) -> str:
    return hashlib.sha256(canonical(roster).encode("utf-8")).hexdigest()


def build_execution_roster(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
) -> list[dict[str, Any]]:
    """Capture the complete immutable execution context in Stage order."""
    from yoke_core.domain.qa_case_execution_context import (
        get_case_execution_context,
    )
    from yoke_core.domain.qa_plan_execution import ordered_plan_requirements

    ordered = ordered_plan_requirements(
        conn,
        item_id=item_id,
        transition_id=transition_id,
    )
    roster: list[dict[str, Any]] = []
    for ordinal, order in enumerate(ordered):
        context = get_case_execution_context(
            conn,
            requirement_id=int(order["requirement_id"]),
        )
        roster.append(
            {
                **context,
                "ordinal": ordinal,
                "case_position": int(order["case_position"]),
                "baseline_position": int(order["baseline_position"]),
            }
        )
    return roster


def _row_dict(cursor: Any, row: Any) -> dict[str, Any] | None:
    if row is None:
        return None
    if hasattr(row, "keys"):
        return {str(key): row[key] for key in row.keys()}
    columns = [
        str(getattr(column, "name", None) or column[0]) for column in cursor.description
    ]
    return dict(zip(columns, row))


def _first_value(row: Any, key: str) -> Any:
    if hasattr(row, "keys"):
        return row[key]
    return row[0]


def live_plan_execution_id(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
) -> str | None:
    """Return the current live execution id across supported row factories."""
    placeholder = marker(conn)
    cursor = conn.execute(
        "SELECT id FROM qa_plan_executions "
        f"WHERE item_id={placeholder} AND transition_id={placeholder} "
        "AND state IN ('active','waiting') ORDER BY created_at DESC LIMIT 1",
        (int(item_id), transition_id),
    )
    row = cursor.fetchone()
    return None if row is None else str(_first_value(row, "id"))


def select_plan_execution(
    conn: Any,
    execution_id: str,
    *,
    lock: bool,
) -> dict[str, Any]:
    """Read and normalize one execution, optionally taking a write lock."""
    if lock and not db_backend.connection_is_postgres(conn):
        if not bool(getattr(conn, "in_transaction", False)):
            conn.execute("BEGIN IMMEDIATE")
    placeholder = marker(conn)
    suffix = " FOR UPDATE" if lock and db_backend.connection_is_postgres(conn) else ""
    cursor = conn.execute(
        f"SELECT * FROM qa_plan_executions WHERE id={placeholder}{suffix}",
        (str(execution_id),),
    )
    row = _row_dict(cursor, cursor.fetchone())
    if row is None:
        raise QaPlanExecutionStateError(f"QA plan execution {execution_id!r} not found")
    row["cursor_ordinal"] = int(row["cursor_ordinal"])
    row["item_id"] = int(row["item_id"])
    if row.get("machine_lease_id") is not None:
        row["machine_lease_id"] = int(row["machine_lease_id"])
    try:
        roster = json.loads(str(row["roster_json"]))
    except (TypeError, ValueError) as exc:
        raise QaPlanExecutionStateError(
            "QA plan execution contains an invalid roster snapshot"
        ) from exc
    if not isinstance(roster, list) or any(
        not isinstance(value, dict) for value in roster
    ):
        raise QaPlanExecutionStateError(
            "QA plan execution contains an invalid roster snapshot"
        )
    row["roster"] = roster
    return row


def lock_plan_execution(conn: Any, execution_id: str) -> dict[str, Any]:
    """Lock and return a durable execution authority row."""
    return select_plan_execution(conn, execution_id, lock=True)


def same_owner(
    execution: Mapping[str, Any],
    *,
    actor_id: str | None,
    session_id: str,
) -> bool:
    stored_actor = (
        str(execution["actor_id"]) if execution.get("actor_id") is not None else None
    )
    return stored_actor == (str(actor_id) if actor_id is not None else None) and str(
        execution["session_id"]
    ) == str(session_id)


def resume_owned_plan_execution(
    conn: Any,
    execution: dict[str, Any],
    *,
    digest: str,
) -> dict[str, Any]:
    """Validate and reactivate a live execution already owned by the caller."""
    if str(execution["roster_digest"]) != digest:
        conn.rollback()
        raise QaPlanExecutionStateError(
            "materialized QA roster changed during execution"
        )
    if execution["state"] == "waiting":
        placeholder = marker(conn)
        now = iso8601_now()
        conn.execute(
            "UPDATE qa_plan_executions SET state='active',"
            f"heartbeat_at={placeholder} WHERE id={placeholder}",
            (now, str(execution["id"])),
        )
        conn.commit()
        return select_plan_execution(conn, str(execution["id"]), lock=False)
    conn.commit()
    return execution


def converge_plan_execution_insert_race(
    conn: Any,
    *,
    item_id: int,
    transition_id: str,
    actor_id: str | None,
    session_id: str,
    digest: str,
    cause: BaseException,
) -> dict[str, Any]:
    """Translate a lost live-row insert race into the domain ownership result."""
    conn.rollback()
    concurrent_id = live_plan_execution_id(
        conn,
        item_id=item_id,
        transition_id=transition_id,
    )
    if concurrent_id is None:
        conn.rollback()
        raise QaPlanExecutionStateError(
            "QA plan execution changed concurrently; begin must be retried"
        ) from cause
    concurrent = lock_plan_execution(conn, concurrent_id)
    if not same_owner(
        concurrent,
        actor_id=actor_id,
        session_id=session_id,
    ):
        conn.rollback()
        raise QaPlanExecutionStateError(
            "another actor or session owns the active QA plan execution"
        ) from cause
    return resume_owned_plan_execution(conn, concurrent, digest=digest)


def require_plan_execution_owner(
    execution: Mapping[str, Any],
    *,
    item_id: int,
    actor_id: str | None,
    session_id: str,
) -> None:
    """Bind every execution mutation to its item, actor, and session."""
    if int(execution["item_id"]) != int(item_id):
        raise QaPlanExecutionStateError("QA plan execution belongs to a different item")
    if not same_owner(
        execution,
        actor_id=actor_id,
        session_id=session_id,
    ):
        raise QaPlanExecutionStateError(
            "QA plan execution belongs to a different actor or session"
        )


def result_rows(conn: Any, execution_id: str) -> list[dict[str, Any]]:
    placeholder = marker(conn)
    cursor = conn.execute(
        "SELECT ordinal,requirement_id,result_json,completed_at "
        "FROM qa_plan_execution_results "
        f"WHERE execution_id={placeholder} ORDER BY ordinal",
        (execution_id,),
    )
    rows = [
        normalized
        for row in cursor.fetchall()
        if (normalized := _row_dict(cursor, row)) is not None
    ]
    results = []
    for row in rows:
        results.append(
            {
                "ordinal": int(row["ordinal"]),
                "requirement_id": int(row["requirement_id"]),
                "result": json.loads(str(row["result_json"])),
                "completed_at": row["completed_at"],
            }
        )
    return results


def plan_execution_view(
    conn: Any,
    execution: Mapping[str, Any],
) -> dict[str, Any]:
    """Return the secret-free resume contract exposed to a client."""
    return {
        "execution_id": str(execution["id"]),
        "item_id": int(execution["item_id"]),
        "transition_id": str(execution["transition_id"]),
        "state": str(execution["state"]),
        "roster_digest": str(execution["roster_digest"]),
        "cursor_ordinal": int(execution["cursor_ordinal"]),
        "machine_lease_id": execution.get("machine_lease_id"),
        "requirements": list(execution["roster"]),
        "results": result_rows(conn, str(execution["id"])),
    }


__all__ = [
    "QaPlanExecutionStateError",
    "build_execution_roster",
    "canonical",
    "converge_plan_execution_insert_race",
    "live_plan_execution_id",
    "lock_plan_execution",
    "marker",
    "plan_execution_view",
    "require_plan_execution_owner",
    "result_rows",
    "resume_owned_plan_execution",
    "roster_digest",
    "same_owner",
    "select_plan_execution",
]
