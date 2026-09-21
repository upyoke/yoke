"""Withdraw a deployment QA wait wake once its subject is settled.

A wait names a run, a stage, and (for item-scoped waits) a member. When
the run is terminal, the member's item is done, or that member's
item-scoped stage is already credited, the instruction in the body is
wrong to follow. Withdrawal is the existing message-cancel path: the
envelope stays on record with a reason, and already-recorded delivery
attempts are left untouched.

The sweep re-evaluates each still-pending wait. Event-driven callers that
already know why the subject settled pass ``reason`` so the cancel does
not depend on a second read of the same fact.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.actors import SYSTEM_COMPONENT_YOKE_CORE, seed_system_actor
from yoke_core.domain.deployment_qa_stage_wake import (
    DEPLOYMENT_QA_STAGE_WAIT_PREFIX,
    RUN_SCOPED_WAIT_TOKEN,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_item_delivery_status import TERMINAL_RUN_STATUSES
from yoke_core.domain.session_message_store import cancel_message_rows
from yoke_core.domain.session_message_types import parse_timestamp, utc_now


#: Item statuses that mean the member is no longer a waiting owner.
_MEMBER_SETTLED_STATUSES = frozenset({"done", "cancelled", "stopped"})


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def parse_deployment_qa_wait_key(
    key: str,
) -> tuple[str, str, Optional[int]] | None:
    """Run id, stage name, and item id (``None`` when the wait is run-scoped)."""
    raw = str(key or "")
    if not raw.startswith(DEPLOYMENT_QA_STAGE_WAIT_PREFIX):
        return None
    parts = raw[len(DEPLOYMENT_QA_STAGE_WAIT_PREFIX) :].split(":")
    if len(parts) < 3:
        return None
    run_id, stage_name, member = parts[0], parts[1], parts[2]
    if not run_id or not stage_name:
        return None
    if member == RUN_SCOPED_WAIT_TOKEN:
        return run_id, stage_name, None
    try:
        return run_id, stage_name, int(member)
    except ValueError:
        return None


def _run_status(conn: Any, run_id: str) -> str | None:
    row = conn.execute(
        f"SELECT status FROM deployment_runs WHERE id={_p(conn)}",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row["status"] if hasattr(row, "keys") else row[0] or "")


def _run_stage(conn: Any, run_id: str) -> str:
    row = conn.execute(
        f"SELECT current_stage FROM deployment_runs WHERE id={_p(conn)}",
        (run_id,),
    ).fetchone()
    if row is None:
        return ""
    return str(row["current_stage"] if hasattr(row, "keys") else row[0] or "")


def _item_status(conn: Any, item_id: int) -> str | None:
    row = conn.execute(
        f"SELECT status FROM items WHERE id={_p(conn)}",
        (int(item_id),),
    ).fetchone()
    if row is None:
        return None
    return str(row["status"] if hasattr(row, "keys") else row[0] or "")


def _member_stage_credited(
    conn: Any, *, run_id: str, item_id: int, current_stage: str
) -> bool:
    from yoke_core.domain.deployment_qa_run_acceptance import current_item_qa

    try:
        answer = current_item_qa(
            conn,
            run_id=run_id,
            item_id=int(item_id),
            current_stage=current_stage,
        )
    except (LookupError, ValueError):
        return False
    return answer is not None and answer.accepted


def deployment_qa_wait_settled_reason(
    conn: Any, *, idempotency_key: str
) -> str | None:
    """Why this wait is no longer owed, or ``None`` if it still is."""
    parsed = parse_deployment_qa_wait_key(idempotency_key)
    if parsed is None:
        return None
    run_id, _stage_name, item_id = parsed
    status = _run_status(conn, run_id)
    if status is None:
        return "run_gone"
    if status in TERMINAL_RUN_STATUSES:
        return f"run_terminal:{status}"
    if item_id is None:
        return None
    item_status = _item_status(conn, item_id)
    if item_status is None:
        return "member_gone"
    if item_status in _MEMBER_SETTLED_STATUSES:
        return f"member_{item_status}"
    if _member_stage_credited(
        conn,
        run_id=run_id,
        item_id=item_id,
        current_stage=_run_stage(conn, run_id),
    ):
        return "member_stage_credited"
    return None


def _pending_wait_rows(
    conn: Any, *, message_id: str | None = None
) -> list[tuple[str, str]]:
    if not _table_exists(conn, "session_messages"):
        # A universe that cannot store Fleet wakes has none to withdraw.
        # Terminal run updates still run here, including on lean test DBs.
        return []
    marker = _p(conn)
    sql = (
        "SELECT m.message_id, m.idempotency_key FROM session_messages m "
        f"WHERE m.cancelled_at IS NULL AND m.idempotency_key LIKE {marker} "
    )
    params: list[Any] = [f"{DEPLOYMENT_QA_STAGE_WAIT_PREFIX}%"]
    if message_id:
        sql += f"AND m.message_id={marker} "
        params.append(message_id)
    sql += (
        "AND EXISTS (SELECT 1 FROM session_message_recipients r "
        "WHERE r.message_id=m.message_id "
        "AND r.state IN ('pending','injected'))"
    )
    rows = conn.execute(sql, tuple(params)).fetchall()
    found: list[tuple[str, str]] = []
    for row in rows:
        found.append(
            (
                str(row["message_id"] if hasattr(row, "keys") else row[0]),
                str(row["idempotency_key"] if hasattr(row, "keys") else row[1] or ""),
            )
        )
    return found


def withdraw_deployment_qa_wait_wakes(
    conn: Any,
    *,
    run_id: str | None = None,
    item_id: int | None = None,
    message_id: str | None = None,
    reason: str | None = None,
    now: datetime | str | None = None,
) -> int:
    """Cancel pending QA wait wakes whose subject is settled.

    ``reason`` skips the per-message re-read: the caller already observed
    the settling event. Without it, each wait is evaluated on its current
    run and member facts. Already-recorded attempts are not rewritten.
    """
    stamp = now if isinstance(now, datetime) else parse_timestamp(now) or utc_now()
    wanted_run = str(run_id or "")
    wanted_item = None if item_id is None else int(item_id)
    actor_id: int | None = None
    withdrawn = 0
    for stored_id, key in _pending_wait_rows(conn, message_id=message_id):
        parsed = parse_deployment_qa_wait_key(key)
        if parsed is None:
            continue
        parsed_run, _stage, parsed_item = parsed
        if wanted_run and parsed_run != wanted_run:
            continue
        if wanted_item is not None and parsed_item != wanted_item:
            continue
        cancel_reason = reason or deployment_qa_wait_settled_reason(
            conn, idempotency_key=key
        )
        if not cancel_reason:
            continue
        if actor_id is None:
            actor_id = seed_system_actor(conn, SYSTEM_COMPONENT_YOKE_CORE)
        cancel_message_rows(
            conn,
            message_id=stored_id,
            actor_id=actor_id,
            reason=cancel_reason,
            cancelled_at=stamp,
        )
        withdrawn += 1
    return withdrawn


__all__ = [
    "deployment_qa_wait_settled_reason",
    "parse_deployment_qa_wait_key",
    "withdraw_deployment_qa_wait_wakes",
]
