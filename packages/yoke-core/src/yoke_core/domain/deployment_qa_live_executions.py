"""What each live deployment QA plan execution is doing right now.

A live execution (``active``, ``waiting``, ``walking`` or
``awaiting_walk_review``) already owns its subject's QA, so the fleet report
and the stage's case lines name it instead of telling anyone to run the case
again. ``waiting`` means the walk is queued for a Test Machine turn, not
walking; its place comes from the one Test Machine queue
(:func:`yoke_core.domain.qa_host_queue.position_text`).

An execution whose owning session recorded its end is not live here: its walk
is the sweep's to settle, and its member is woken as usual. A presentation
reads every presented run's live executions, and the queue, once.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.qa_plan_execution_schema import LIVE_PLAN_EXECUTION_SQL
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.schema_work_claim_sql import scope_text_sql

QUEUED = "waiting"
WALKING_STATES = frozenset({"active", "walking"})
AWAITING_REVIEW = "awaiting_walk_review"


def _rows(conn: Any, runs: tuple[str, ...]) -> list[dict[str, Any]]:
    machine = scope_text_sql(conn, "wc.scope", "test_machine")
    markers = ",".join("%s" for _ in runs)
    return [
        dict(row)
        for row in query_rows(
            conn,
            "SELECT e.id AS execution_id, e.deployment_run_id AS run_id, "
            "e.deployment_stage AS stage, e.deployment_member_item_id AS item_id, "
            "e.execution_target_digest AS digest, e.session_id, e.state, "
            f"{machine} AS test_machine FROM qa_plan_executions e "
            "LEFT JOIN work_claims wc ON wc.id=e.test_machine_lease_id "
            f"WHERE e.deployment_run_id IN ({markers}) "
            f"AND e.state IN ({LIVE_PLAN_EXECUTION_SQL}) AND NOT EXISTS ("
            "SELECT 1 FROM harness_sessions s WHERE s.session_id=e.session_id "
            "AND s.ended_at IS NOT NULL) ORDER BY e.session_id, e.id",
            runs,
        )
    ]


def live_executions(conn: Any, run_id: str) -> list[dict[str, Any]]:
    """Every live execution on this run, any stage or subject."""
    from yoke_core.domain.deployment_qa_presentation_facts import presented_run_ids
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read

    runs = presented_run_ids(conn, str(run_id))
    if not runs:
        return _rows(conn, (str(run_id),))
    rows = presentation_read(
        conn, ("qa_live_executions", tuple(runs)), lambda: _rows(conn, tuple(runs))
    )
    return [row for row in rows if str(row["run_id"]) == str(run_id)]


def covering_execution(
    conn: Any,
    *,
    run_id: str,
    stage_name: str,
    member_item_id: int | None,
    execution_target_digest: str,
) -> dict[str, Any] | None:
    """The live execution already walking this exact subject and target."""
    return next(
        (
            row
            for row in live_executions(conn, run_id)
            if str(row["stage"]) == str(stage_name)
            and int(row["item_id"] or 0) == int(member_item_id or 0)
            and str(row["digest"] or "") == str(execution_target_digest)
        ),
        None,
    )


def queue_places(conn: Any) -> dict[str, str]:
    """Each queued execution's "queued for <machine>, <place>" phrase."""
    from yoke_core.domain.deployment_qa_presentation_reads import presentation_read
    from yoke_core.domain.qa_host_queue import (
        position_text,
        queue_entries,
        waits_for_text,
    )

    def read() -> dict[str, str]:
        if not _table_exists(conn, "qa_test_machine_waits"):
            return {}
        return {
            str(entry["execution_id"]): (
                f"queued for {waits_for_text(entry)}, {position_text(entry['places'])}"
            )
            for entry in queue_entries(conn)
            if entry["execution_id"]
        }

    return presentation_read(conn, ("qa_host_queue_places",), read)


def activity(conn: Any, row: Mapping[str, Any]) -> str:
    """What this live execution is doing, in one phrase."""
    state = str(row["state"])
    if state == QUEUED:
        return queue_places(conn).get(
            str(row["execution_id"]), "queued for a Test Machine turn"
        )
    if state == AWAITING_REVIEW:
        return "mission walk handed back; its review is pending"
    machine = row.get("test_machine")
    return "mission walk in progress" + (f" on {machine}" if machine else "")


def execution_line(conn: Any, row: Mapping[str, Any]) -> str:
    """Name the execution and what it is doing, for a case's wait line."""
    return (
        f"plan execution {row['execution_id']} ({row['state']}) already owns it: "
        f"{activity(conn, row)}; it settles when that execution finishes"
    )


def case_next_step(
    conn: Any, *, verdict: str, review: Any, live: Any, recipe: str
) -> str:
    """What answers one unpassed case: its review, its live walk, or a run.

    A walking execution's mission is still capturing, so its line says so and
    names no review command until hand-back.
    """
    if review is not None and review.state == "walking":
        return f"; {review.next_action()}"
    if review is not None:
        return (
            ""
            if verdict
            else f"; its capture awaits independent review: {review.next_action()}"
        )
    if live is not None:
        return f"; {execution_line(conn, live)}"
    return f"; run `{recipe}`"


__all__ = [
    "AWAITING_REVIEW",
    "case_next_step",
    "QUEUED",
    "WALKING_STATES",
    "activity",
    "covering_execution",
    "execution_line",
    "live_executions",
    "queue_places",
]
