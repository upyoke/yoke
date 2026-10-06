"""Retain unjudged QA attempts unless a settled successor owns their answer."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_qa_source_obligation import source_obligation_consumed
from yoke_core.domain.qa_obligation_settlement import requirement_retracted_at_select


def unsettled_supersession_runs(
    conn: Any, item_id: int, runs: list[Any]
) -> list[tuple[Any, str]]:
    """Filter closed superseded attempts, and name an unanswered successor.

    Completion is required on the old attempt: a replacement cannot discharge
    a process that still owns live execution. The successor's latest evidence
    must pass or its obligation must be discharged; a link alone is no proof.
    Read the item's requirements together so many old attempts cost one query.
    """
    if not any(row[5] for row in runs):
        return [(row, "") for row in runs]
    marker = "%s" if db_backend.connection_is_postgres(conn) else "?"
    rows = conn.execute(
        "SELECT q.id, q.waived_at, q.superseded_by_requirement_id, "
        f"{requirement_retracted_at_select(conn, 'q')}, "
        "r.verdict, r.completed_at, r.execution_status, q.qa_phase, q.deployment_run_id "
        "FROM qa_requirements q LEFT JOIN qa_runs r ON r.id = ("
        "SELECT latest.id FROM qa_runs latest WHERE latest.qa_requirement_id = q.id "
        "ORDER BY latest.id DESC LIMIT 1) "
        f"WHERE q.item_id = {marker}",
        (int(item_id),),
    ).fetchall()
    requirements = {int(row[0]): row for row in rows}
    source_settlement: dict[int, bool] = {}

    def open_successor(requirement_id: int) -> int | None:
        seen: set[int] = set()
        while requirement_id not in seen:
            seen.add(requirement_id)
            row = requirements.get(requirement_id)
            if row is None:
                return requirement_id
            if row[1] or row[3]:
                return None
            if row[7] == "post_deploy" and not row[8]:
                if requirement_id not in source_settlement:
                    source_settlement[requirement_id] = source_obligation_consumed(
                        conn, item_id=item_id, source_requirement_id=requirement_id
                    )
                if source_settlement[requirement_id]:
                    return None
                if row[2]:
                    requirement_id = int(row[2])
                    continue
                return requirement_id
            if row[5] and row[6] not in {"queued", "running", "waiting"}:
                if row[4] == "pass":
                    return None
                if row[2]:
                    requirement_id = int(row[2])
                    continue
            return requirement_id
        return requirement_id

    unsettled = []
    for row in runs:
        successor_id = row[5]
        if not successor_id:
            unsettled.append((row, ""))
            continue
        pending_id = open_successor(int(successor_id))
        closed = bool(row[4]) and row[2] not in {"queued", "running", "waiting"}
        if closed and pending_id is None:
            continue
        detail = (
            f"; successor requirement {pending_id} is unsettled "
            f"(finish it or discharge it with yoke qa requirement waive --help)"
            if pending_id is not None
            else ""
        )
        unsettled.append((row, detail))
    return unsettled
