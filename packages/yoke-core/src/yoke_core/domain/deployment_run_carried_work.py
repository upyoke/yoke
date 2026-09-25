"""Derive and persist the source changes carried by a deployment run.

Run membership answers which items the pipeline owns. Carried work answers a
different question: which trunk changes exist between the preceding release
lineage and this run's lineage. The result therefore lives on the run and
never writes ``deployment_run_items`` or item lifecycle state.

A run ships one commit per project it carries — its own, plus every project
a stage binds — so the same comparison runs once per project, each against
that project's own recorded commit and the commit the preceding run recorded
for it. The bound answers travel under ``bound_projects`` so one record still
says everything one release carried.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Mapping

from yoke_core.domain.deployment_run_bound_sources import (
    BOUND_SOURCES_FIELD,
    bound_project_shas,
    bound_sources_recorded,
    parse_bound_sources,
)
from yoke_core.domain.deployment_run_project_carried_work import (
    CARRIED_WORK_SCHEMA,
    derive_project_carried_work,
    empty_carried_work,
)
from yoke_core.domain.function_target_row_project import slug_for_project_id
from yoke_core.domain.json_helper import dumps_compact, loads_text


CARRIED_WORK_FIELD = "carried_work"


def parse_carried_work(value: Any) -> dict[str, Any] | None:
    """Return one stored carried-work object, or ``None`` for no record."""
    if value in (None, ""):
        return None
    if isinstance(value, Mapping):
        return dict(value)
    try:
        parsed = loads_text(str(value))
    except (TypeError, ValueError):
        return None
    return dict(parsed) if isinstance(parsed, Mapping) else None


def _cell(row: Any, key: str, index: int) -> Any:
    return row[key] if hasattr(row, "keys") else row[index]


def _bound_sources_column(conn: Any) -> str:
    """Name the stored record, or a constant empty one before converge."""
    if bound_sources_recorded(conn):
        return BOUND_SOURCES_FIELD
    return f"'' AS {BOUND_SOURCES_FIELD}"


def _previous_run(conn: Any, run_id: str, project_id: int, environment_id: Any):
    return conn.execute(
        f"SELECT id,project_id,release_lineage,{_bound_sources_column(conn)},"
        "completed_at "
        "FROM deployment_runs "
        "WHERE project_id=%s AND status='succeeded' AND id<>%s "
        "AND target_environment_id IS NOT DISTINCT FROM %s "
        "ORDER BY completed_at DESC NULLS LAST,created_at DESC,id DESC LIMIT 1",
        (project_id, run_id, environment_id),
    ).fetchone()


def derive_carried_work(
    conn: Any,
    run_id: str,
    *,
    repo_root: str | Path | None = None,
) -> dict[str, Any]:
    """Derive every project's carried set for one run, own project first."""
    row = conn.execute(
        "SELECT project_id,target_environment_id,release_lineage,"
        f"{_bound_sources_column(conn)} FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    project_id = int(_cell(row, "project_id", 0))
    environment_id = _cell(row, "target_environment_id", 1)
    release_lineage = str(_cell(row, "release_lineage", 2) or "").strip()
    previous = _previous_run(conn, run_id, project_id, environment_id)
    payload = derive_project_carried_work(
        conn,
        run_id,
        project_id=project_id,
        release_lineage=release_lineage,
        previous=previous,
        repo_root=repo_root,
    )
    bound = bound_project_shas(parse_bound_sources(_cell(row, BOUND_SOURCES_FIELD, 3)))
    payload["bound_projects"] = [
        dict(
            derive_project_carried_work(
                conn,
                run_id,
                project_id=bound_project_id,
                release_lineage=bound[bound_project_id],
                previous=previous,
            ),
            project_id=bound_project_id,
            project=slug_for_project_id(conn, bound_project_id),
        )
        for bound_project_id in sorted(bound)
        if bound_project_id != project_id
    ]
    return payload


def derive_carried_work_safely(conn: Any, run_id: str) -> dict[str, Any]:
    """Derive without writing, and answer in the same shape when it cannot.

    Both callers need a payload rather than an exception: the completion
    record has to say why it is empty, and the pre-approval snapshot has to
    tell an approver that the contents could not be derived rather than let a
    git failure abort the decision request. The derivation happens inside a
    savepoint so a failed read leaves the caller's transaction usable.
    """
    conn.execute("SAVEPOINT carried_work_derivation")
    try:
        payload = derive_carried_work(conn, run_id)
    except Exception as exc:  # noqa: BLE001 - callers record named emptiness
        conn.execute("ROLLBACK TO SAVEPOINT carried_work_derivation")
        conn.execute("RELEASE SAVEPOINT carried_work_derivation")
        return empty_carried_work(
            "derivation_failed",
            "Repair the named checkout or metadata read, clear this field, and retry.",
            run_id=run_id,
            error_type=type(exc).__name__,
        )
    conn.execute("RELEASE SAVEPOINT carried_work_derivation")
    return payload


def record_carried_work(conn: Any, run_id: str) -> dict[str, Any]:
    """Write a forward-only carried-work record in the caller's transaction."""
    row = conn.execute(
        "SELECT carried_work FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    existing = parse_carried_work(_cell(row, CARRIED_WORK_FIELD, 0))
    if existing is not None:
        _require_bound_project_coverage(conn, run_id, existing)
        return existing
    payload = derive_carried_work_safely(conn, run_id)
    conn.execute(
        "UPDATE deployment_runs SET carried_work=%s WHERE id=%s",
        (dumps_compact(payload), run_id),
    )
    return payload


def carried_work_for_enrollment(conn: Any, run_id: str) -> dict[str, Any]:
    """Derive provisionally until the run has recorded every bound source."""
    row = conn.execute(
        "SELECT carried_work FROM deployment_runs WHERE id=%s", (run_id,)
    ).fetchone()
    if row is None:
        raise LookupError(f"deployment run {run_id!r} not found")
    existing = parse_carried_work(_cell(row, CARRIED_WORK_FIELD, 0))
    if existing is not None:
        _require_bound_project_coverage(conn, run_id, existing)
        return existing
    return derive_carried_work_safely(conn, run_id)


def _require_bound_project_coverage(
    conn: Any, run_id: str, payload: dict[str, Any]
) -> None:
    row = conn.execute(
        f"SELECT {_bound_sources_column(conn)} FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    assert row is not None
    expected = set(bound_project_shas(parse_bound_sources(row[0])))
    actual = {int(entry["project_id"]) for entry in payload.get("bound_projects") or []}
    if expected != actual:
        raise ValueError(
            f"deployment run {run_id!r} carried_work omits recorded bound "
            f"project source(s) {sorted(expected - actual)}; its attribution "
            "was recorded before bound sources. Cancel this run and create a "
            "new one so membership is derived from every pinned source"
        )


__all__ = [
    "CARRIED_WORK_FIELD",
    "CARRIED_WORK_SCHEMA",
    "carried_work_for_enrollment",
    "derive_carried_work",
    "derive_project_carried_work",
    "derive_carried_work_safely",
    "parse_carried_work",
    "record_carried_work",
]
