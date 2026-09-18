"""The release a session's held item is riding, and that member's own QA.

A session card already says where its item is in its own workflow. It could
not say where that item is in the release carrying it, so a worker parked
until a stage deploys looked identical to one parked on a review, and the
only way to tell was to open the run.

Two rules shape what this answers:

Statuses travel as they are stored. A run's ``stage`` and ``status`` are
values other surfaces record, gate on and search by, so this projection
carries them unchanged rather than translating them into a friendlier
vocabulary a reader cannot match against anything else.

The newest run is not automatically the current delivery. A cancelled or
failed release stays in the history of every item it carried, so reporting
the newest row as "the release" would present an abandoned candidate as the
one in flight. The live run is the newest non-terminal one; when there is
none, the newest terminal run is reported as history and says so, so a
reader can tell "riding this release" from "the last one it rode".

The item half is this member's standing at the item QA stage now answering
for it — not its workflow stage, which the card's stage strip already draws,
and not the release's whole QA ledger. It reads the same per-stage acceptance
the release-to-done gate reads, narrowed twice: to item-scoped stages,
because a run-scoped gate is the batch's shared wait that the run half
already reports, and to a stage the run has reached, because a production
check nobody has run yet is not this member's outstanding work. Two members
of one run held by one session keep their own standings.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_item_flow_resolution import item_completion_flow
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
        "SELECT dri.item_id, dr.id, dr.status, dr.current_stage, dr.created_at, "
        "dr.flow "
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
                "flow": str(row["flow"] or ""),
            }
        )
    return grouped


def _chosen_run(
    runs: list[dict[str, Any]], *, completion_flow: str,
) -> dict[str, Any] | None:
    """The selected-flow release this item is riding, or the last one it rode."""
    matching = [
        run for run in runs
        if completion_flow and run.get("flow") == completion_flow
    ] if completion_flow else []
    for run in matching:
        if run["status"] not in TERMINAL_RUN_STATUSES:
            return {**run, "live": True}
    return {**matching[0], "live": False} if matching else None


def _member_qa(
    conn: Any, subjects: Sequence[tuple[str, int, str]]
) -> dict[tuple[str, int], dict[str, Any]]:
    """Each member's standing at the item QA stage now answering for it.

    The authority is the same per-stage acceptance the release gate reads, so
    "accepted" means here exactly what it means there. Two narrowings make it
    an item fact rather than a release one: only item-scoped stages count,
    because a run-scoped gate is the batch's shared wait and the run half
    already reports it; and only a stage the run has reached counts, because
    a production check nobody has run yet is not this member's outstanding
    work. Within that stage, history stays history — a case that failed and
    was rerun to a pass is accepted.
    """
    from yoke_core.domain.deployment_qa_run_acceptance import current_item_qa

    standing: dict[tuple[str, int], dict[str, Any]] = {}
    for run_id, item_id, current_stage in subjects:
        try:
            answer = current_item_qa(
                conn, run_id=run_id, item_id=item_id, current_stage=current_stage
            )
        except (LookupError, ValueError):
            # An unreadable gate is not a passing one; the card says nothing
            # rather than implying this member's QA is clear.
            continue
        if answer is None:
            continue
        standing[(run_id, item_id)] = {
            "state": answer.state,
            "stage": answer.stage,
            "reason": answer.reason,
        }
    return standing


def primary_item_delivery_by_session(
    conn: Any, rows: list[dict[str, Any]]
) -> dict[str, Mapping[str, Any]]:
    """Project the release carrying each roster session's primary held item."""
    selected = primary_item_ids(conn, rows)
    item_ids = tuple(dict.fromkeys(selected.values()))
    by_item = _member_runs(conn, item_ids)
    chosen = {}
    for item_id, runs in by_item.items():
        run = _chosen_run(
            runs, completion_flow=item_completion_flow(conn, item_id),
        )
        if run is not None:
            chosen[item_id] = run
    qa = _member_qa(
        conn,
        [(run["run_id"], item_id, run["stage"]) for item_id, run in chosen.items()],
    )
    projected: dict[str, Mapping[str, Any]] = {}
    for session_id, item_id in selected.items():
        run = chosen.get(item_id)
        if run is None:
            continue
        standing = qa.get((run["run_id"], item_id))
        projected[session_id] = {
            **run,
            # Absent is absent, not a pass: a release that has reached no
            # item QA stage answering for this member has nothing to report
            # rather than nothing wrong.
            "item_qa": standing["state"] if standing else None,
            "item_qa_stage": standing["stage"] if standing else None,
            "item_qa_reason": standing["reason"] if standing else None,
        }
    return projected


__all__ = ["TERMINAL_RUN_STATUSES", "primary_item_delivery_by_session"]
