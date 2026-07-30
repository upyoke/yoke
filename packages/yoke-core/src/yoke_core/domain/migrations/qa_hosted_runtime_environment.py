"""Materialize the hosted Yoke runtime as a project environment."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.qa_execution_environment_target import (
    runtime_environment_name,
)
from yoke_core.domain.qa_hosted_runtime_identity import (
    CANONICAL_RUNTIME_SITE_ID,
    CANONICAL_RUNTIME_SITE_NAME,
    RUNTIME_ALIASES,
    canonical_environment_id,
    eligible_plan_environment_rows,
    require_runtime_site_owner,
)
from yoke_core.domain.schema_common import _table_exists


MIGRATION_NAME = "qa_hosted_runtime_environment"


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _runtime() -> str:
    selected = runtime_environment_name()
    for canonical, aliases in RUNTIME_ALIASES.items():
        if selected in aliases:
            return canonical
    raise RuntimeError(
        f"hosted QA runtime environment must be stage or prod, got {selected!r}"
    )


def _yoke_project_id(conn: Any) -> int | None:
    rows = conn.execute(
        "SELECT id FROM projects WHERE slug='yoke' ORDER BY id"
    ).fetchall()
    if not rows:
        return None
    if len(rows) > 1:
        raise RuntimeError("hosted QA runtime environment found multiple yoke projects")
    row = rows[0]
    return int(row["id"] if hasattr(row, "keys") else row[0])


def _has_active_plan(conn: Any, *, project_id: int) -> bool:
    marker = _p(conn)
    return (
        conn.execute(
            "SELECT 1 FROM qa_plans "
            f"WHERE project_id={marker} AND retired_at IS NULL LIMIT 1",
            (project_id,),
        ).fetchone()
        is not None
    )


def _ensure_site(conn: Any, *, project_id: int) -> int:
    marker = _p(conn)
    try:
        owner = require_runtime_site_owner(conn, plan_project_id=project_id)
    except ValueError as exc:
        raise RuntimeError(str(exc)) from exc
    if owner is None:
        conn.execute(
            "INSERT INTO sites(id,project_id,name,created_at,settings) "
            f"VALUES({marker},{marker},{marker},CURRENT_TIMESTAMP,{marker})",
            (
                CANONICAL_RUNTIME_SITE_ID,
                project_id,
                CANONICAL_RUNTIME_SITE_NAME,
                "{}",
            ),
        )
        return project_id
    return owner


def _runtime_environment_rows(
    conn: Any,
    *,
    project_id: int,
    runtime: str,
) -> list[Any]:
    rows = eligible_plan_environment_rows(conn, plan_project_id=project_id)
    return [
        row
        for row in rows
        if str(row["environment_name"]).lower() in RUNTIME_ALIASES[runtime]
    ]


def _ensure_environment(
    conn: Any,
    *,
    project_id: int,
    site_owner_id: int,
    runtime: str,
) -> None:
    matches = _runtime_environment_rows(
        conn,
        project_id=project_id,
        runtime=runtime,
    )
    if len(matches) == 1:
        return
    if len(matches) > 1:
        raise RuntimeError(
            f"yoke project {project_id} has multiple {runtime!r} environments"
        )
    if site_owner_id != project_id:
        raise RuntimeError(
            "shared hosted QA site has no canonical "
            f"{runtime!r} environment; host-project mutation is not authorized"
        )
    marker = _p(conn)
    environment_id = canonical_environment_id(runtime)
    assert environment_id is not None
    existing = conn.execute(
        f"SELECT site,name FROM environments WHERE id={marker}",
        (environment_id,),
    ).fetchone()
    if existing is not None:
        site = str(existing["site"] if hasattr(existing, "keys") else existing[0])
        name = str(existing["name"] if hasattr(existing, "keys") else existing[1])
        raise RuntimeError(
            f"hosted QA environment id {environment_id!r} is already "
            f"bound to site {site!r} as {name!r}"
        )
    conn.execute(
        "INSERT INTO environments(id,site,name,created_at,settings) "
        f"VALUES({marker},{marker},{marker},CURRENT_TIMESTAMP,{marker})",
        (environment_id, CANONICAL_RUNTIME_SITE_ID, runtime, "{}"),
    )


def apply(conn: Any) -> None:
    """Ensure every hosted Yoke tenant declares its own runtime target."""
    missing = [
        table
        for table in ("projects", "sites", "environments", "qa_plans")
        if not _table_exists(conn, table)
    ]
    if missing:
        raise RuntimeError(
            "hosted QA runtime environment requires deployed tables: "
            + ", ".join(missing)
        )
    runtime = _runtime()
    project_id = _yoke_project_id(conn)
    if project_id is None or not _has_active_plan(conn, project_id=project_id):
        return
    site_owner_id = _ensure_site(conn, project_id=project_id)
    _ensure_environment(
        conn,
        project_id=project_id,
        site_owner_id=site_owner_id,
        runtime=runtime,
    )


def invariants(conn: Any) -> None:
    """Require one runtime-compatible environment owned by the Yoke project."""
    runtime = _runtime()
    project_id = _yoke_project_id(conn)
    if project_id is None or not _has_active_plan(conn, project_id=project_id):
        return
    try:
        owner = require_runtime_site_owner(conn, plan_project_id=project_id)
    except ValueError as exc:
        raise AssertionError(str(exc)) from exc
    if owner is None:
        raise AssertionError(f"hosted QA site {CANONICAL_RUNTIME_SITE_ID!r} is absent")
    if (
        len(
            _runtime_environment_rows(
                conn,
                project_id=project_id,
                runtime=runtime,
            )
        )
        != 1
    ):
        raise AssertionError(
            f"yoke project {project_id} does not have one {runtime!r} environment"
        )


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
