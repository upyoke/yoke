"""Which succeeded releases a delivery question may be asked about.

The delivery ladder answers whether a release carried one item. Before it can
ask containment anything, something has to decide which releases are even
candidates, and that decision differs by what the item stores.

An item with a selected flow is asked about that flow's runs, plus the runs
of another project that bound this project's source and recorded the commit
they resolved — both ship this repository, so both can carry the merge.

An item that stores no flow has no such list, so its own project's releases
to a persistent environment stand in: any flow qualifies, because the flow
was never the fact that mattered, while an ephemeral run does not, because
nothing it reached outlives it. Staying inside the item's own project is
deliberate — a release of some other project is that project's delivery,
however it resolved this source.

Both walks hand back the same row shape, newest first, so the caller asks one
question of one repository: the newest release contains the most merges, so
the first rung answers almost every item, and the limit only bounds how far
back an unusually old landing is chased.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.deployment_run_project_sources import (
    carrying_runs_for_project,
)
from yoke_core.domain.schema_common import _column_exists


#: The ``deployment_runs.target_tier`` that outlives the run. Its counterpart,
#: ``ephemeral``, is a per-run preview that delivers nothing durable.
PERSISTENT_TARGET_TIER = "persistent"

#: Both walks select these three, in this order, so one row reader serves both.
_RELEASE_COLUMNS = (
    "SELECT id, COALESCE(release_lineage, '') AS release_lineage, "
    "COALESCE(completed_at, '') AS completed_at FROM deployment_runs "
)
_NEWEST_FIRST = "ORDER BY completed_at DESC, created_at DESC, id DESC LIMIT "


def sql_marker(conn: Any) -> str:
    """The parameter placeholder this connection's engine expects."""
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def row_cell(row: Any, key: str, position: int) -> Any:
    """One column, whether the engine handed back a mapping or a tuple."""
    return row[key] if hasattr(row, "keys") else row[position]


def _releases(rows: Any) -> list[dict[str, Any]]:
    return [
        {
            "id": str(row_cell(row, "id", 0) or ""),
            "release_lineage": str(row_cell(row, "release_lineage", 1) or ""),
            "completed_at": str(row_cell(row, "completed_at", 2) or ""),
        }
        for row in rows
    ]


def succeeded_flow_runs(
    conn: Any, *, project_id: int, flow: str, limit: int = 10
) -> list[dict[str, Any]]:
    """Recent succeeded releases of this item's own flow that shipped it.

    Carrying runs of another project join the list: each carries the commit
    that release holds for THIS project, which is the candidate to ask about
    rather than the carrier's own lineage.
    """
    marker = sql_marker(conn)
    releases = _releases(
        conn.execute(
            _RELEASE_COLUMNS
            + f"WHERE project_id = {marker} AND flow = {marker} "
            "AND status = 'succeeded' "
            + _NEWEST_FIRST
            + str(int(limit)),
            (int(project_id), flow),
        ).fetchall()
    )
    releases.extend(
        {
            "id": run["id"],
            "release_lineage": run["source_sha"],
            "completed_at": run["completed_at"],
        }
        for run in carrying_runs_for_project(conn, int(project_id))
    )
    releases.sort(key=lambda release: release["completed_at"], reverse=True)
    return releases[: int(limit)]


def succeeded_persistent_runs(
    conn: Any, *, project_id: int, limit: int = 10
) -> list[dict[str, Any]]:
    """Recent succeeded releases of this project to a persistent environment.

    What a flow-less item is asked about instead of "runs of the selected
    flow": any flow of the item's own project qualifies, so long as the run
    reached a destination that still exists after it.
    """
    if not _column_exists(conn, "deployment_runs", "target_tier"):
        return []
    marker = sql_marker(conn)
    return _releases(
        conn.execute(
            _RELEASE_COLUMNS
            + f"WHERE project_id = {marker} AND status = 'succeeded' "
            f"AND target_tier = {marker} "
            + _NEWEST_FIRST
            + str(int(limit)),
            (int(project_id), PERSISTENT_TARGET_TIER),
        ).fetchall()
    )


__all__ = [
    "PERSISTENT_TARGET_TIER",
    "row_cell",
    "sql_marker",
    "succeeded_flow_runs",
    "succeeded_persistent_runs",
]
