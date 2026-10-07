"""Which commit a run pinned for one project, and which runs pinned one.

Every delivery question a project asks of a release — was my merge in it, is
this item's card looking at the right candidate, may this item be a member —
is the same question about one commit. A run answers it for its own project
from ``release_lineage`` and for every project it binds from the commit it
recorded at start, so callers ask here instead of deciding per project which
column to read.

What a run *delivered* for a project can differ from what it pinned: a
promotion that materializes a version pin onto a bound project's trunk ships
that release output, so the bound project's target serves the output commit,
not the bound one. Served-identity questions ask
:func:`delivered_source_sha`; containment and checkout questions keep asking
for the pin.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.deployment_run_bound_sources import (
    BOUND_SOURCES_FIELD,
    bound_project_shas,
    bound_sources_recorded,
    parse_bound_sources,
)
from yoke_core.domain.deployment_run_release_output import project_release_outputs


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _stored_column(conn: Any, alias: str = "") -> str:
    """Select the stored record, or a constant empty one before converge."""
    prefix = f"{alias}." if alias else ""
    if bound_sources_recorded(conn):
        return f"COALESCE({prefix}{BOUND_SOURCES_FIELD},'')"
    return "''"


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


def delivered_source_sha(run: Mapping[str, Any], project_id: int) -> str:
    """The commit this run delivered for ``project_id``, or ``""``.

    The run's own project serves its release lineage. A bound project serves
    the last commit the run recorded producing for it -- a release pin it
    materialized onto that project's trunk -- and, where the run produced
    nothing there, the commit it bound.
    """
    own = run.get("project_id")
    if own is not None and int(own) == int(project_id):
        return str(run.get("release_lineage") or "").strip()
    payload = parse_bound_sources(run.get(BOUND_SOURCES_FIELD))
    outputs = project_release_outputs(payload).get(int(project_id), ())
    if outputs:
        return outputs[-1]["commit_sha"]
    return bound_project_shas(payload).get(int(project_id), "")


_RUN_SOURCE_FACTS_KEY = "deployment_run_source"


def invalidate_run_source_facts(conn: Any, run_id: str) -> None:
    from yoke_core.domain.schema_read_scope import discard_read

    discard_read(conn, (_RUN_SOURCE_FACTS_KEY, str(run_id)))


def run_source_facts(conn: Any, run_id: str) -> dict[str, Any] | None:
    """Share recorded lineage/bindings and immutable flow inside one operation."""
    from yoke_core.domain.schema_read_scope import shared_read

    def read():
        row = conn.execute(
            "SELECT dr.project_id,COALESCE(dr.release_lineage,'') AS release_lineage,"
            f"{_stored_column(conn, 'dr')} AS {BOUND_SOURCES_FIELD},dr.flow,df.stages "
            "FROM deployment_runs dr LEFT JOIN deployment_flows df ON df.id=dr.flow "
            f"WHERE dr.id={_p(conn)}",
            (run_id,),
        ).fetchone()
        if row is None:
            return None
        return {
            key: _cell(row, key, index)
            for index, key in enumerate(
                ("project_id", "release_lineage", BOUND_SOURCES_FIELD, "flow", "stages")
            )
        }

    return shared_read(conn, (_RUN_SOURCE_FACTS_KEY, str(run_id)), read)


def run_source_sha(conn: Any, run_id: str, project_id: int) -> str:
    """The commit this run pinned for a project, with operation-local sharing."""
    run = run_source_facts(conn, run_id)
    return recorded_source_sha(run, int(project_id)) if run is not None else ""


def run_delivered_sha(conn: Any, run_id: str, project_id: int) -> str:
    """The commit this run delivered for a project, with operation-local sharing."""
    run = run_source_facts(conn, run_id)
    return delivered_source_sha(run, int(project_id)) if run is not None else ""


def carried_project_ids(conn: Any, run_id: str) -> tuple[int, ...]:
    """Every project this run ships code for: its own, then each bound one."""
    run = run_source_facts(conn, run_id)
    if run is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    own = int(run["project_id"])
    payload = parse_bound_sources(run[BOUND_SOURCES_FIELD])
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

    if not bound_sources_recorded(conn) or not _column_exists(
        conn, "deployment_runs", "target_environment_id"
    ):
        return []
    marker = _p(conn)
    rows = conn.execute(
        f"SELECT dr.id,dr.project_id,COALESCE(dr.{BOUND_SOURCES_FIELD},'') AS "
        f"{BOUND_SOURCES_FIELD},COALESCE(dr.release_lineage,'') AS release_lineage,"
        "COALESCE(dr.completed_at,'') AS completed_at,"
        "COALESCE(dr.carried_work,'') AS carried_work,"
        "COALESCE(e.name,'') AS environment_name,"
        "COALESCE(dr.flow,'') AS flow,"
        "COALESCE(dr.composition_frozen_at,'') AS composition_frozen_at "
        "FROM deployment_runs dr "
        "LEFT JOIN environments e ON e.id=dr.target_environment_id "
        f"WHERE dr.status='succeeded' AND dr.project_id<>{marker} "
        f"AND COALESCE(dr.{BOUND_SOURCES_FIELD},'')<>'' "
        "ORDER BY dr.completed_at DESC,dr.created_at DESC,dr.id DESC",
        (int(project_id),),
    ).fetchall()
    carrying: list[dict[str, Any]] = []
    for row in rows:
        if (
            environment_name
            and str(_cell(row, "environment_name", 6) or "") != environment_name
        ):
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
                # The flow that ran, so a reader with no flow of its own can
                # still name the one that shipped it.
                "flow": str(_cell(row, "flow", 7) or ""),
                "composition_frozen_at": str(
                    _cell(row, "composition_frozen_at", 8) or ""
                ),
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
    "delivered_source_sha",
    "environment_name",
    "recorded_source_sha",
    "run_delivered_sha",
    "run_source_sha",
]
