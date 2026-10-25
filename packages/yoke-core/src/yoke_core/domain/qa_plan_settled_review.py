"""A persisted agent-verdict batch closes review; a passing verdict settles QA.

The review wake is queued when capture reaches awaiting review. The verdict
can land before that wake is delivered. Delivery then cancels it, whatever
the verdict. Re-entering the plan runner reprints passing verdicts and leaves
those settled requirements out of any new roster. A requirement whose newest
verdict is fail or undetermined, or that has no verdict, stays open, so the
existing admission path (including ``--replaces``) starts a fresh capture.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping

from yoke_contracts.timestamps import parse_instant, utc_now
from yoke_core.domain.qa_constants import case_outcome_for_verdict
from yoke_core.domain.qa_plan_execution_result_state import aggregate_state
from yoke_core.domain.qa_plan_execution_store import marker, select_plan_execution
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_message_store import cancel_message_rows

REVIEW_WAKE_PREFIX = "qa-plan-agent-review:"
SETTLED_REVIEW_WAKE_REASON = "qa_review_verdict_recorded"


def settled_review_wake_reason(execution_id: str) -> str:
    """Named cancel reason, plus the recovery the owner should follow."""
    return (
        f"{SETTLED_REVIEW_WAKE_REASON}: execution {execution_id} already has a "
        "persisted verdict batch, so its review is complete. Rerun "
        "`yoke qa plan run`: it reprints passing verdicts and captures fresh "
        "evidence for failed or undetermined requirements."
    )


def _review_tables(conn: Any) -> bool:
    return _table_exists(conn, "qa_plan_review_bundles") and _table_exists(
        conn, "qa_plan_review_verdicts"
    )


def _value(row: Any, key: str, index: int) -> Any:
    if hasattr(row, "keys"):
        return row[key]
    return row[index]


def execution_has_persisted_verdict_batch(conn: Any, execution_id: str) -> bool:
    """True when this execution's review bundle has stored verdict rows."""
    if not _review_tables(conn):
        return False
    placeholder = marker(conn)
    row = conn.execute(
        "SELECT 1 FROM qa_plan_review_bundles b "
        "JOIN qa_plan_review_verdicts v ON v.bundle_id=b.id "
        f"WHERE b.execution_id={placeholder} AND b.state='completed' LIMIT 1",
        (str(execution_id),),
    ).fetchone()
    return row is not None


def _subject_filter(
    conn: Any,
    *,
    item_id: int | None,
    transition_id: str | None,
    deployment_run_id: str | None,
    deployment_stage: str | None,
    deployment_member_item_id: int | None,
) -> tuple[str, tuple[Any, ...]]:
    placeholder = marker(conn)
    if item_id is not None:
        return (
            f"e.item_id={placeholder} AND e.transition_id={placeholder}",
            (int(item_id), str(transition_id)),
        )
    return (
        f"e.deployment_run_id={placeholder} "
        f"AND COALESCE(e.deployment_stage,'')={placeholder} "
        f"AND COALESCE(e.deployment_member_item_id,0)={placeholder}",
        (
            str(deployment_run_id),
            deployment_stage or "",
            deployment_member_item_id or 0,
        ),
    )


def _persisted_verdicts(
    conn: Any,
    requirement_ids: list[int],
    *,
    digest: str,
    subject_sql: str,
    subject_params: tuple[Any, ...],
) -> tuple[str | None, dict[int, dict[str, Any]]]:
    placeholder = marker(conn)
    slots = ", ".join(placeholder for _ in requirement_ids)
    rows = conn.execute(
        "SELECT v.requirement_id, v.verdict, v.rationale, v.review_run_id, "
        "b.execution_id, v.capture_run_id FROM qa_plan_review_verdicts v "
        "JOIN qa_plan_review_bundles b ON b.id=v.bundle_id "
        "JOIN qa_plan_executions e ON e.id=b.execution_id "
        f"WHERE b.state='completed' AND e.execution_target_digest={placeholder} "
        f"AND {subject_sql} AND v.requirement_id IN ({slots}) "
        "ORDER BY v.created_at DESC, v.requirement_id",
        (digest, *subject_params, *requirement_ids),
    ).fetchall()
    from yoke_core.domain.qa_latest_execution import latest_executions

    # A batch verdict settles a requirement only while it judges the newest
    # capture: a later capture (a stopped walk's, say) reopens the question.
    current = {
        requirement_id: int(row["id"])
        for requirement_id, row in latest_executions(conn, requirement_ids).items()
    }
    newest_execution_id = None
    newest: set[int] = set()
    verdicts: dict[int, dict[str, Any]] = {}
    for row in rows:
        requirement_id = int(_value(row, "requirement_id", 0))
        if requirement_id in newest:
            continue
        newest.add(requirement_id)
        if str(_value(row, "verdict", 1)) != "pass":
            continue
        judged = {
            int(_value(row, "review_run_id", 3)),
            int(_value(row, "capture_run_id", 5)),
        }
        if current.get(requirement_id) not in judged:
            continue
        if newest_execution_id is None:
            newest_execution_id = str(_value(row, "execution_id", 4))
        verdicts[requirement_id] = {
            "requirement_id": requirement_id,
            "verdict": str(_value(row, "verdict", 1)),
            "rationale": str(_value(row, "rationale", 2)),
            "review_run_id": int(_value(row, "review_run_id", 3)),
        }
    return newest_execution_id, verdicts


def open_unsettled_roster(
    conn: Any,
    roster: list[dict[str, Any]],
    *,
    item_id: int | None,
    transition_id: str | None,
    deployment_run_id: str | None,
    deployment_stage: str | None,
    deployment_member_item_id: int | None,
) -> tuple[dict[str, Any] | None, list[dict[str, Any]]]:
    """Drop requirements whose newest recorded verdict is a pass.

    Requirements a stopped walk's pending review owns drop out too; when
    nothing else remains the run refuses with ``qa_plan_nothing_owed``.

    When nothing remains, return the settled execution carrying those
    verdicts so the runner reprints them. Otherwise return the roster still
    eligible to capture, including failed or undetermined requirements.
    """
    if not roster or not _review_tables(conn):
        return None, roster
    from yoke_core.domain.qa_pending_agent_review import pending_review_requirements
    from yoke_core.domain.qa_plan_execution_target_snapshot import (
        execution_target_for_roster,
    )

    held = pending_review_requirements(
        conn, [int(row["requirement_id"]) for row in roster], stopped_only=True
    )
    if held:
        # A stopped walk's pending review owns these verdicts; recapturing
        # them would race that review.
        kept = [row for row in roster if int(row["requirement_id"]) not in held]
        if not kept:
            from yoke_core.domain.qa_plan_nothing_owed import nothing_owed

            raise nothing_owed(
                conn,
                roster_size=len(roster),
                deployment_run_id=deployment_run_id,
                deployment_stage=deployment_stage,
                held=held,
            )
        roster = [{**row, "ordinal": index} for index, row in enumerate(kept)]

    _target, digest = execution_target_for_roster(roster)
    if not digest:
        return None, roster
    subject_sql, subject_params = _subject_filter(
        conn,
        item_id=item_id,
        transition_id=transition_id,
        deployment_run_id=deployment_run_id,
        deployment_stage=deployment_stage,
        deployment_member_item_id=deployment_member_item_id,
    )
    execution_id, verdicts = _persisted_verdicts(
        conn,
        [int(row["requirement_id"]) for row in roster],
        digest=str(digest),
        subject_sql=subject_sql,
        subject_params=subject_params,
    )
    if not verdicts or execution_id is None:
        return None, roster
    kept = [row for row in roster if int(row["requirement_id"]) not in verdicts]
    if kept:
        if len(kept) != len(roster):
            kept = [{**row, "ordinal": index} for index, row in enumerate(kept)]
        return None, kept
    stored = select_plan_execution(conn, execution_id, lock=False)
    stored["settled_review"] = [
        verdicts[requirement_id] for requirement_id in sorted(verdicts)
    ]
    stored["remaining_requirement_count"] = 0
    return stored, []


def settled_review_run_result(execution: Mapping[str, Any]) -> dict[str, Any]:
    """The plan-runner result that reprints a batch and captures nothing."""
    verdicts = [dict(row) for row in execution["settled_review"]]
    state = "passed"
    results = []
    for verdict in verdicts:
        result = {
            "requirement_id": int(verdict["requirement_id"]),
            "verdict": verdict["verdict"],
            "rationale": verdict["rationale"],
            "qa_run_id": int(verdict["review_run_id"]),
            "case_outcome": case_outcome_for_verdict(str(verdict["verdict"])),
        }
        results.append(result)
        state = aggregate_state(state, result)
    recovery = (
        "Passing review verdicts are already recorded and reprinted here. "
        "The pass remains accepted when the lane or deployed build advances."
    )
    return {
        "execution_id": str(execution.get("execution_id") or execution["id"]),
        "item_id": execution.get("item_id"),
        "deployment_run_id": execution.get("deployment_run_id"),
        "deployment_stage": execution.get("deployment_stage"),
        "deployment_member_item_id": execution.get("deployment_member_item_id"),
        "transition_id": execution.get("transition_id"),
        "state": state,
        "review_status": "settled",
        "requirement_count": len(results),
        "executed_count": 0,
        "results": results,
        "verdicts": verdicts,
        "review_bundle": None,
        "recovery": recovery,
    }


def _pending_review_wakes(conn: Any, *, execution_id: str) -> list[str]:
    if not _table_exists(conn, "session_messages"):
        return []
    placeholder = marker(conn)
    # A stopped walk's review wakes under ``ID:owner`` or ``ID:MEMBER``.
    rows = conn.execute(
        "SELECT m.message_id FROM session_messages m "
        f"WHERE m.cancelled_at IS NULL AND (m.idempotency_key={placeholder} "
        f"OR m.idempotency_key LIKE {placeholder}) "
        "AND EXISTS (SELECT 1 FROM session_message_recipients r "
        "WHERE r.message_id=m.message_id AND r.state IN ('pending','injected'))",
        (
            f"{REVIEW_WAKE_PREFIX}{execution_id}",
            f"{REVIEW_WAKE_PREFIX}{execution_id}:%",
        ),
    ).fetchall()
    return [str(_value(row, "message_id", 0)) for row in rows]


def withdraw_settled_agent_review_wakes(
    conn: Any,
    *,
    execution_id: str,
    now: datetime | str | None = None,
) -> int:
    """Cancel this execution's review wakes once it has a verdict batch.

    The review submission that persists the batch calls this; no request
    path sweeps every open review wake.
    """
    if not _review_tables(conn):
        return 0
    if not execution_has_persisted_verdict_batch(conn, execution_id):
        return 0
    current = parse_instant(utc_now() if now is None else now)
    withdrawn = 0
    for message_id in _pending_review_wakes(conn, execution_id=execution_id):
        cancel_message_rows(
            conn,
            message_id=message_id,
            actor_id=None,
            reason=settled_review_wake_reason(execution_id),
            cancelled_at=current,
        )
        withdrawn += 1
    return withdrawn


__all__ = [
    "REVIEW_WAKE_PREFIX",
    "SETTLED_REVIEW_WAKE_REASON",
    "execution_has_persisted_verdict_batch",
    "open_unsettled_roster",
    "settled_review_run_result",
    "settled_review_wake_reason",
    "withdraw_settled_agent_review_wakes",
]
