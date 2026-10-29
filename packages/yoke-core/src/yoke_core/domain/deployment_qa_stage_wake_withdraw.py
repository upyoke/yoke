"""Withdraw a deployment QA wait wake once its subject is settled.

A wait names a run, a stage, and (for item-scoped waits) a member. When
the run is terminal, the member's item is done, or that member's
item-scoped stage is already credited, the instruction in the body is
wrong to follow. Withdrawal is the existing message-cancel path: the
envelope stays on record with a reason, and already-recorded delivery
attempts are left untouched.

Withdrawal is event-driven only: the code that settles the subject passes
its ``reason``. No request path sweeps open waits, because re-reading QA
acceptance per open wait grows with the fleet and ran inside the
acknowledge and relay-claim transactions.
"""

from __future__ import annotations

from yoke_contracts.timestamps import parse_instant

from datetime import datetime
from typing import Any, Callable, Iterable, Optional

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_qa_stage_wake import (
    DEPLOYMENT_QA_STAGE_WAIT_PREFIX,
    RUN_SCOPED_WAIT_TOKEN,
)
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_message_store import cancel_messages
from yoke_core.domain.session_message_types import utc_now


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
    if member in {RUN_SCOPED_WAIT_TOKEN, "plan-groups"}:
        return run_id, stage_name, None
    try:
        return run_id, stage_name, int(member)
    except ValueError:
        return None


def _pending_wait_rows(conn: Any, *, pattern: str) -> list[tuple[str, str]]:
    if not _table_exists(conn, "session_messages"):
        # A universe that cannot store Fleet wakes has none to withdraw.
        # Terminal run updates still run here, including on lean test DBs.
        return []
    # The caller re-checks the parsed key exactly; LIKE only narrows.
    rows = conn.execute(
        "SELECT m.message_id, m.idempotency_key FROM session_messages m "
        f"WHERE m.cancelled_at IS NULL AND m.idempotency_key LIKE {_p(conn)} "
        "AND EXISTS (SELECT 1 FROM session_message_recipients r "
        "WHERE r.message_id=m.message_id "
        "AND r.state IN ('pending','injected'))",
        (pattern,),
    ).fetchall()
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
    run_id: str,
    reason: str,
    item_ids: Iterable[int] | None = None,
    now: datetime | str | None = None,
) -> int:
    """Cancel one run's pending QA wait wakes because ``reason`` settled them.

    The caller is the settling event (run terminal, member removed, member
    stage credited), so nothing is re-read here: the work is one read of
    this run's waits and one cancel. ``item_ids`` narrows to those members'
    item-scoped waits. Already-recorded attempts are not rewritten.
    """
    stamp = parse_instant(utc_now() if now is None else now)
    wanted_items = None if item_ids is None else {int(value) for value in item_ids}
    return _cancel_matching(
        conn,
        pattern=f"{DEPLOYMENT_QA_STAGE_WAIT_PREFIX}{run_id}:%",
        keep=lambda parsed: parsed[0] == str(run_id)
        and (wanted_items is None or parsed[2] in wanted_items),
        reason=reason,
        now=stamp,
    )


def withdraw_member_qa_wait_wakes(
    conn: Any,
    *,
    item_id: int,
    reason: str,
    now: datetime | str | None = None,
) -> int:
    """Cancel this item's item-scoped QA waits in every run (item closed)."""
    stamp = parse_instant(utc_now() if now is None else now)
    return _cancel_matching(
        conn,
        pattern=f"{DEPLOYMENT_QA_STAGE_WAIT_PREFIX}%:%:{int(item_id)}:%",
        keep=lambda parsed: parsed[2] == int(item_id),
        reason=reason,
        now=stamp,
    )


def withdraw_plan_group_wait_wakes(conn: Any, run_id: str, stage_name: str) -> int:
    """A changed group roster withdraws consolidated and per-member notices."""
    consolidated = _cancel_matching(conn,
        pattern=f"{DEPLOYMENT_QA_STAGE_WAIT_PREFIX}{run_id}:{stage_name}:plan-groups:%",
        keep=lambda parsed: parsed[:2] == (str(run_id), str(stage_name)),
        reason="Plan group closed", now=utc_now())
    return consolidated + _cancel_matching(conn,
        pattern=f"{DEPLOYMENT_QA_STAGE_WAIT_PREFIX}{run_id}:{stage_name}:%:plan-group-%",
        keep=lambda parsed: parsed[:2] == (str(run_id), str(stage_name))
        and parsed[2] is not None,
        reason="Plan group closed", now=utc_now())


def _cancel_matching(
    conn: Any,
    *,
    pattern: str,
    keep: Callable[[tuple[str, str, Optional[int]]], bool],
    reason: str,
    now: datetime,
) -> int:
    message_ids = []
    for stored_id, key in _pending_wait_rows(conn, pattern=pattern):
        parsed = parse_deployment_qa_wait_key(key)
        if parsed is not None and keep(parsed):
            message_ids.append(stored_id)
    if message_ids:
        cancel_messages(
            conn,
            message_ids=message_ids,
            actor_id=None,
            reason=reason,
            cancelled_at=now,
        )
    return len(message_ids)


__all__ = [
    "parse_deployment_qa_wait_key",
    "withdraw_deployment_qa_wait_wakes",
    "withdraw_member_qa_wait_wakes",
]
