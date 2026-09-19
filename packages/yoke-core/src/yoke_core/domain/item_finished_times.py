"""When an item's life ended, and which stages mean it ended.

Terminal and finished are two readings of the same status, and they are not
the same set. ``item_terminal_resources.terminal_stage_ids`` answers "may this
item still hold execution resources", so it includes ``stopped`` and releases
claims, lanes and environments on the way in. But ``stopped`` is a pause —
`lifecycle.md` calls it "Work halted unexpectedly or intentionally paused" —
so an item sitting at it has not finished, and counting it as finished work
would report a halt as an accomplishment.

Finished is the narrower reading this module owns: the stages a definition
itself declares terminal, plus ``cancelled``, which ends an item outright.
Every display and count that asks "did this item finish, and when" resolves it
from here against the item's own pinned workflow version, so no surface
re-derives the answer from a status list of its own.

The *when* comes from ``item_status_transitions``, the first-class state table
every status writer writes at mutation time — the table that replaced the
retired ``ItemStatusChanged`` envelope scans. It is not the events ledger, so
reading it keeps events write-only disposable telemetry. An item's finishing
moment is the transition that put it into the status it currently holds.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, FrozenSet, List, Tuple

from yoke_core.domain.frontier_workflow_versions import (
    FrontierWorkflowVersions,
    load_frontier_workflow_versions,
)
from yoke_core.domain.workflow_runtime import WorkflowRuntime

#: ``cancelled`` ends an item; the engine's other terminal stage, ``stopped``,
#: deliberately does not appear here. See the module docstring.
ENGINE_FINISHED_STAGE_IDS: FrozenSet[str] = frozenset({"cancelled"})

#: How far back a "finished recently" reading looks.
FINISHED_WINDOW = timedelta(hours=24)

#: One item-level transition into the status the item still holds. Matching on
#: ``to_status = i.status`` is what makes this the *finishing* transition
#: rather than any earlier move, and it needs no status list of its own.
_FINISHING_TRANSITION_SQL = (
    "SELECT t.item_id AS item_id, MAX(t.created_at) AS finished_at "
    "FROM item_status_transitions t "
    "JOIN items i ON i.id = t.item_id "
    "WHERE t.task_num IS NULL AND t.to_status = i.status "
    "AND t.created_at >= %s "
    "GROUP BY t.item_id"
)


def finished_stage_ids(runtime: WorkflowRuntime) -> FrozenSet[str]:
    """Return the stages at which an item on this workflow has finished."""
    return runtime.terminal_stage_ids | ENGINE_FINISHED_STAGE_IDS


def is_finished(runtime: WorkflowRuntime, status: str) -> bool:
    """Whether *status* is a finished stage for this item's own definition."""
    return str(status or "").strip().lower() in finished_stage_ids(runtime)


def window_cutoff(window: timedelta = FINISHED_WINDOW) -> str:
    """Return the ISO instant a finished-recently reading starts from."""
    return (datetime.now(timezone.utc) - window).strftime("%Y-%m-%dT%H:%M:%SZ")


def finished_status_clause(
    versions: FrontierWorkflowVersions,
    marker: str,
) -> Tuple[str, List[Any]]:
    """Render the SQL predicate matching rows at a finished stage.

    Terminal-ness is a property of the item's own pinned definition, so the
    predicate is rendered per version rather than from one status list that
    would be wrong for any workflow declaring a different ending. Versions
    sharing a finished set share a fragment, so the SQL stays short on a
    project with many published versions.
    """
    groups: Dict[FrozenSet[str], List[int]] = {}
    for version_id, runtime in versions.runtimes.items():
        groups.setdefault(finished_stage_ids(runtime), []).append(version_id)

    fragments: List[str] = []
    params: List[Any] = []
    for statuses, version_ids in groups.items():
        ordered_versions = sorted(version_ids)
        ordered_statuses = sorted(statuses)
        version_marks = ", ".join(marker for _ in ordered_versions)
        status_marks = ", ".join(marker for _ in ordered_statuses)
        fragments.append(
            f"(i.workflow_version_id IN ({version_marks})"
            f" AND i.status IN ({status_marks}))"
        )
        params.extend(ordered_versions)
        params.extend(ordered_statuses)
    if not fragments:
        # No published version can declare an ending, so no row is finished.
        return "1 = 0", []
    return " OR ".join(fragments), params


def finished_window_clause(
    conn: Any,
    marker: str = "%s",
    window: timedelta = FINISHED_WINDOW,
) -> Tuple[str, List[Any]]:
    """Render the predicate keeping unfinished rows and recent finishers.

    The finishing transition is looked up per candidate row rather than
    carried on the item, because ``item_status_transitions`` already owns that
    fact for every item back to the table's first row and storing it twice
    would only invite drift.
    """
    versions = load_frontier_workflow_versions(conn)
    finished_sql, finished_params = finished_status_clause(versions, marker)
    clause = (
        f"(NOT ({finished_sql}) OR EXISTS ("
        "SELECT 1 FROM item_status_transitions t "
        "WHERE t.item_id = i.id AND t.task_num IS NULL "
        f"AND t.to_status = i.status AND t.created_at >= {marker}))"
    )
    return clause, [*finished_params, window_cutoff(window)]


def finished_times_in_window(
    conn: Any,
    window: timedelta = FINISHED_WINDOW,
) -> Dict[int, str]:
    """Return ``item_id -> finishing instant`` for the window, in one query.

    The read is bounded by the window rather than by the roster, so a board
    of any size costs the same one statement. Rows for items that merely
    changed stage recently are returned too and cost nothing; the caller
    resolves finished-ness against each item's own definition.
    """
    cursor = conn.execute(_FINISHING_TRANSITION_SQL, (window_cutoff(window),))
    times: Dict[int, str] = {}
    for row in cursor.fetchall():
        values = dict(row) if hasattr(row, "keys") else None
        item_id = int(values["item_id"] if values else row[0])
        finished_at = str(values["finished_at"] if values else row[1])
        times[item_id] = finished_at
    return times


__all__ = [
    "ENGINE_FINISHED_STAGE_IDS",
    "FINISHED_WINDOW",
    "finished_stage_ids",
    "finished_status_clause",
    "finished_times_in_window",
    "finished_window_clause",
    "is_finished",
    "window_cutoff",
]
