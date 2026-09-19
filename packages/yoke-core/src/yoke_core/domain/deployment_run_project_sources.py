"""Which commit a run pinned for one project, and which runs pinned one.

Every delivery question a project asks of a release — was my merge in it, is
this item's card looking at the right candidate, may this item be a member —
is the same question about one commit. A run answers it for its own project
from ``release_lineage`` and for every project it binds from the commit it
recorded at start, so callers ask here instead of deciding per project which
column to read.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.deployment_run_bound_sources import (
    BOUND_SOURCES_FIELD,
    bound_project_shas,
    parse_bound_sources,
)


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def recorded_source_sha(run: Mapping[str, Any], project_id: int) -> str:
    """The commit this run pinned for ``project_id``, or ``""``.

    One question with one answer for every project a run carries: its own
    release lineage, or the commit it bound for somebody else's project.
    """
    own = run.get("project_id")
    if own is not None and int(own) == int(project_id):
        return str(run.get("release_lineage") or "").strip()
    payload = parse_bound_sources(run.get(BOUND_SOURCES_FIELD))
    return bound_project_shas(payload).get(int(project_id), "")


def run_source_sha(conn: Any, run_id: str, project_id: int) -> str:
    """The commit ``run_id`` pinned for ``project_id``, read from the run."""
    marker = _p(conn)
    row = conn.execute(
        f"SELECT project_id,COALESCE(release_lineage,'') AS release_lineage,"
        f"COALESCE({BOUND_SOURCES_FIELD},'') AS {BOUND_SOURCES_FIELD} "
        f"FROM deployment_runs WHERE id={marker}",
        (run_id,),
    ).fetchone()
    if row is None:
        return ""
    return recorded_source_sha(
        {
            "project_id": _cell(row, "project_id", 0),
            "release_lineage": _cell(row, "release_lineage", 1),
            BOUND_SOURCES_FIELD: _cell(row, BOUND_SOURCES_FIELD, 2),
        },
        int(project_id),
    )


def carried_project_ids(conn: Any, run_id: str) -> tuple[int, ...]:
    """Every project this run ships code for: its own, then each bound one."""
    marker = _p(conn)
    row = conn.execute(
        f"SELECT project_id,COALESCE({BOUND_SOURCES_FIELD},'') AS "
        f"{BOUND_SOURCES_FIELD} FROM deployment_runs WHERE id={marker}",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    own = int(_cell(row, "project_id", 0))
    payload = parse_bound_sources(_cell(row, BOUND_SOURCES_FIELD, 1))
    bound = [pid for pid in bound_project_shas(payload) if pid != own]
    return (own, *sorted(bound))


def carrying_runs_for_project(
    conn: Any,
    project_id: int,
    *,
    environment_name: str = "",
) -> list[dict[str, Any]]:
    """Succeeded runs of other projects that shipped ``project_id``'s code.

    These are the releases a project's own run list cannot see: the carrier
    belongs to another project and ran another project's flow, yet the build
    it produced contains this project's commit. Newest first, each row
    carrying the exact commit the run recorded for this project.

    ``environment_name`` keeps the answer to one release line. A carrier
    ships the bound source to its own target environment, and the consumer
    environment serving it is the one of the same name — the same name the
    stage already passes through to the bound project's release.
    """
    from yoke_core.domain.schema_common import _column_exists

    if not all(
        _column_exists(conn, "deployment_runs", column)
        for column in (BOUND_SOURCES_FIELD, "target_environment_id")
    ):
        return []
    marker = _p(conn)
    rows = conn.execute(
        f"SELECT dr.id,dr.project_id,COALESCE(dr.{BOUND_SOURCES_FIELD},'') AS "
        f"{BOUND_SOURCES_FIELD},COALESCE(dr.release_lineage,'') AS release_lineage,"
        "COALESCE(dr.completed_at,'') AS completed_at,"
        "COALESCE(dr.carried_work,'') AS carried_work,"
        "COALESCE(e.name,'') AS environment_name "
        "FROM deployment_runs dr "
        "LEFT JOIN environments e ON e.id=dr.target_environment_id "
        f"WHERE dr.status='succeeded' AND dr.project_id<>{marker} "
        f"AND COALESCE(dr.{BOUND_SOURCES_FIELD},'')<>'' "
        "ORDER BY dr.completed_at DESC,dr.created_at DESC,dr.id DESC",
        (int(project_id),),
    ).fetchall()
    carrying: list[dict[str, Any]] = []
    for row in rows:
        if environment_name and str(
            _cell(row, "environment_name", 6) or ""
        ) != environment_name:
            continue
        sha = recorded_source_sha(
            {
                "project_id": _cell(row, "project_id", 1),
                "release_lineage": _cell(row, "release_lineage", 3),
                BOUND_SOURCES_FIELD: _cell(row, BOUND_SOURCES_FIELD, 2),
            },
            int(project_id),
        )
        if not sha:
            continue
        carrying.append(
            {
                "id": str(_cell(row, "id", 0) or ""),
                "project_id": int(_cell(row, "project_id", 1)),
                "source_sha": sha,
                "completed_at": str(_cell(row, "completed_at", 4) or ""),
                "carried_work": _cell(row, "carried_work", 5),
            }
        )
    return carrying


def environment_name(conn: Any, environment_id: Any) -> str:
    """The name of one environment row, or ``""`` when it names none."""
    if environment_id is None:
        return ""
    row = conn.execute(
        f"SELECT name FROM environments WHERE id={_p(conn)}",
        (environment_id,),
    ).fetchone()
    return str(_cell(row, "name", 0) or "") if row is not None else ""


__all__ = [
    "carried_project_ids",
    "carrying_runs_for_project",
    "environment_name",
    "recorded_source_sha",
    "run_source_sha",
]
