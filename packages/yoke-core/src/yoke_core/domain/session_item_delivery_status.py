"""The release a session's held item is riding, and that member's own QA.

A session card already says where its item is in its own workflow. It could
not say where that item is in the release carrying it, so a worker parked
until a stage deploys looked identical to one parked on a review, and the
only way to tell was to open the run.

Two rules shape what this answers:

Statuses travel as they are stored. A run's ``status`` and a member's QA
outcome are enum values other surfaces record, gate on and search by, so this
projection carries them unchanged rather than translating them into a
friendlier vocabulary a reader cannot match against anything else.

The newest run is not automatically the current delivery. A cancelled or
failed release stays in the history of every item it carried, so reporting
the newest row as "the release" would present an abandoned candidate as the
one in flight. The live run is the newest non-terminal one; when there is
none, the newest terminal run is reported as history and says so, so a
reader can tell "riding this release" from "the last one it rode".

The item half is the member's own QA state inside that run — not its
workflow stage, which the card's stage strip already draws. Two members of
one run held by one session keep their own QA states, because they are
separate executions.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.qa_execution_proof import qa_run_outcome
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_item_stage_states import primary_item_ids

#: Run statuses that mean the release is over. Anything else is in flight.
TERMINAL_RUN_STATUSES = frozenset({"succeeded", "failed", "cancelled", "stopped"})


def _marker(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _member_runs(conn: Any, item_ids: Sequence[int]) -> dict[int, list[dict[str, Any]]]:
    """Every run each item is a member of, newest first."""
    if not item_ids:
        return {}
    if not all(
        _table_exists(conn, name)
        for name in ("deployment_runs", "deployment_run_items")
    ):
        return {}
    marker = _marker(conn)
    placeholders = ", ".join(marker for _ in item_ids)
    rows = conn.execute(
        "SELECT dri.item_id, dr.id, dr.status, dr.current_stage, dr.created_at "
        "FROM deployment_runs dr "
        "JOIN deployment_run_items dri ON dri.run_id = dr.id "
        f"WHERE dri.item_id IN ({placeholders}) "
        "ORDER BY dr.created_at DESC, dr.id DESC",
        tuple(int(value) for value in item_ids),
    ).fetchall()
    grouped: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(int(row["item_id"]), []).append(
            {
                "run_id": str(row["id"]),
                "status": str(row["status"] or ""),
                "stage": str(row["current_stage"] or ""),
            }
        )
    return grouped


def _chosen_run(runs: list[dict[str, Any]]) -> dict[str, Any] | None:
    """The release this item is riding, or the last one it rode."""
    for run in runs:
        if run["status"] not in TERMINAL_RUN_STATUSES:
            return {**run, "live": True}
    return {**runs[0], "live": False} if runs else None


def _member_qa(
    conn: Any, pairs: Sequence[tuple[str, int]]
) -> dict[tuple[str, int], str]:
    """The QA outcome each member recorded inside its own run.

    A member with several cases in one run reports the one a reader must act
    on first: a failure outranks a review, which outranks work still running,
    which outranks a pass. Reporting only the newest row would hide a failed
    case behind a later passing one.
    """
    if not pairs or not all(
        _table_exists(conn, name) for name in ("qa_requirements", "qa_runs")
    ):
        return {}
    marker = _marker(conn)
    run_ids = sorted({run_id for run_id, _ in pairs})
    item_ids = sorted({item_id for _, item_id in pairs})
    run_places = ", ".join(marker for _ in run_ids)
    item_places = ", ".join(marker for _ in item_ids)
    rows = conn.execute(
        "SELECT q.deployment_run_id, q.deployment_member_item_id, q.waived_at, "
        "r.verdict, r.case_outcome, r.execution_status "
        "FROM qa_requirements q "
        "LEFT JOIN qa_runs r ON r.qa_requirement_id = q.id "
        f"WHERE q.deployment_run_id IN ({run_places}) "
        f"AND q.deployment_member_item_id IN ({item_places}) "
        "ORDER BY q.id, r.id",
        (*run_ids, *item_ids),
    ).fetchall()
    #: Lower sorts first: what a reader has to answer for comes before what
    #: is already settled.
    urgency = {
        "failed": 0,
        "needs_review": 1,
        "unsure": 1,
        "undetermined": 1,
        "running": 2,
        "waiting": 2,
        "queued": 3,
        "waived": 4,
        "passed": 5,
    }
    worst: dict[tuple[str, int], str] = {}
    for row in rows:
        key = (
            str(row["deployment_run_id"]),
            int(row["deployment_member_item_id"]),
        )
        outcome = qa_run_outcome(row)
        current = worst.get(key)
        if current is None or urgency.get(outcome, 3) < urgency.get(current, 3):
            worst[key] = outcome
    return worst


def primary_item_delivery_by_session(
    conn: Any, rows: list[dict[str, Any]]
) -> dict[str, Mapping[str, Any]]:
    """Project the release carrying each roster session's primary held item."""
    selected = primary_item_ids(conn, rows)
    by_item = _member_runs(conn, tuple(dict.fromkeys(selected.values())))
    chosen = {
        item_id: run
        for item_id, runs in by_item.items()
        if (run := _chosen_run(runs)) is not None
    }
    qa = _member_qa(conn, [(run["run_id"], item_id) for item_id, run in chosen.items()])
    projected: dict[str, Mapping[str, Any]] = {}
    for session_id, item_id in selected.items():
        run = chosen.get(item_id)
        if run is None:
            continue
        projected[session_id] = {
            **run,
            # Absent QA is absent, not a pass: a member with no recorded case
            # in this run has nothing to report rather than nothing wrong.
            "item_qa": qa.get((run["run_id"], item_id)),
        }
    return projected


__all__ = ["TERMINAL_RUN_STATUSES", "primary_item_delivery_by_session"]
