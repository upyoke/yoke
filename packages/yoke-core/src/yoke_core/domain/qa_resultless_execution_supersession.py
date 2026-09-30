"""Supersede an item-level QA execution that recorded no result at all.

A member walking its own release QA opens an item-level
``qa_plan_executions`` row. When the run that finally delivers that member
scopes its own item QA, the run-bound execution is the one that produces
evidence — and the older item-level row stays live, owned by a session
parked on the release wait, holding nothing but its own existence. The
terminal QA settlement gate reads any live item-level execution as
unsettled, so the member can never close: the walk that would abort the row
is the walk that already finished elsewhere, and the stale-heartbeat reaper
deliberately skips a parked owner's executions because silence is not
absence there.

Superseding is safe here precisely because the row recorded nothing. An
execution whose cursor never advanced and which owns no
``qa_plan_execution_results`` row has produced no evidence, so aborting it
discards none. One that did record a result keeps blocking, and its own
walker still owns it.

The abort is only offered to a member whose run-scoped QA for this run is
already satisfied. Without that, a live execution is the member's real
outstanding work and must keep refusing.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.qa_plan_execution_schema import (
    LIVE_PLAN_EXECUTION_SQL,
    QA_PLAN_EXECUTION_RESULT_TABLE,
    QA_PLAN_EXECUTION_TABLE,
    TERMINAL_PLAN_EXECUTION_STATES,
)
from yoke_core.domain.schema_common import _table_exists

#: Stored as the aborted execution's ``release_reason``, so the durable row
#: itself carries why it was settled by something other than its walker.
SUPERSESSION_REASON = "superseded-by-run-scoped-item-qa"


def _placeholder(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def resultless_item_executions(conn: Any, *, item_id: int) -> list[str]:
    """Live item-level executions for this item that recorded nothing.

    Resultless is read two ways that must agree: the cursor never left the
    first case, and no result row was ever written. A row failing either
    test carries evidence and is deliberately absent from this list.
    """
    if not _table_exists(conn, QA_PLAN_EXECUTION_TABLE):
        return []
    marker = _placeholder(conn)
    results_clause = (
        f"AND NOT EXISTS (SELECT 1 FROM {QA_PLAN_EXECUTION_RESULT_TABLE} r "
        f"WHERE r.execution_id = e.id) "
        if _table_exists(conn, QA_PLAN_EXECUTION_RESULT_TABLE)
        else ""
    )
    rows = conn.execute(
        f"SELECT e.id FROM {QA_PLAN_EXECUTION_TABLE} e "
        f"WHERE e.item_id = {marker} AND e.deployment_run_id IS NULL "
        f"AND e.state IN ({LIVE_PLAN_EXECUTION_SQL}) "
        f"AND e.cursor_ordinal = 0 {results_clause}"
        "ORDER BY e.created_at, e.id",
        (int(item_id),),
    ).fetchall()
    return [str(row["id"] if hasattr(row, "keys") else row[0]) for row in rows]


def supersede_resultless_item_executions(
    conn: Any, *, item_id: int, run_id: str, public_ref: str
) -> list[str]:
    """Abort every resultless item-level execution holding this member open.

    Returns one operator-readable line per execution that could not be
    superseded — empty when nothing blocked or every blocker was aborted.
    A member whose run-scoped QA is not yet satisfied is left untouched: its
    live execution is real outstanding work, not residue.
    """
    from yoke_core.domain.no_obligation_member_close_out import (
        satisfied_delivery_member,
    )

    if not satisfied_delivery_member(conn, item_id=int(item_id), run_id=str(run_id)):
        return []
    from yoke_core.domain.qa_plan_execution_lifecycle import finish_plan_execution
    from yoke_core.domain.qa_plan_execution_store import (
        QaPlanExecutionStateError,
        lock_plan_execution,
    )

    unresolved: list[str] = []
    for execution_id in resultless_item_executions(conn, item_id=int(item_id)):
        try:
            execution = lock_plan_execution(conn, execution_id)
            if str(execution["state"]) in TERMINAL_PLAN_EXECUTION_STATES:
                conn.rollback()
                continue
            finish_plan_execution(
                conn,
                execution,
                state="aborted",
                reason=SUPERSESSION_REASON,
            )
        except QaPlanExecutionStateError as exc:
            conn.rollback()
            unresolved.append(
                f"plan execution #{execution_id} recorded no result but could "
                f"not be superseded: {exc}. Abort it with `yoke qa plan abort "
                f"--item {public_ref} --execution-id {execution_id} --reason "
                f'"{SUPERSESSION_REASON}"` while its item claim is held; '
                f"run {run_id} then settles on its own"
            )
            continue
        print(
            f"QA plan execution {execution_id} recorded no result and was "
            f"superseded by run {run_id}'s own item QA."
        )
    return unresolved


__all__ = [
    "SUPERSESSION_REASON",
    "resultless_item_executions",
    "supersede_resultless_item_executions",
]
