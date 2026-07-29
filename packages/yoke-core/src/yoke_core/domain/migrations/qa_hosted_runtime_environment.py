"""Materialize the hosted Yoke runtime as a project environment."""

from __future__ import annotations

from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.qa_execution_environment_target import (
    runtime_environment_name,
)
from yoke_core.domain.schema_common import _table_exists


MIGRATION_NAME = "qa_hosted_runtime_environment"
_SITE_ID = "yoke-api"
_SITE_NAME = "Yoke API"
_ALIASES = {
    "prod": frozenset({"prod", "production"}),
    "stage": frozenset({"stage", "staging"}),
}


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _runtime() -> str:
    selected = runtime_environment_name()
    for canonical, aliases in _ALIASES.items():
        if selected in aliases:
            return canonical
    raise RuntimeError(
        f"hosted QA runtime environment must be stage or prod, got {selected!r}"
    )


def _yoke_project_id(conn: Any) -> int:
    rows = conn.execute(
        "SELECT id FROM projects WHERE slug='yoke' ORDER BY id"
    ).fetchall()
    if len(rows) != 1:
        raise RuntimeError(
            "hosted QA runtime environment requires exactly one yoke project"
        )
    row = rows[0]
    return int(row["id"] if hasattr(row, "keys") else row[0])


def _ensure_site(conn: Any, *, project_id: int) -> None:
    marker = _p(conn)
    row = conn.execute(
        f"SELECT project_id FROM sites WHERE id={marker}",
        (_SITE_ID,),
    ).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO sites(id,project_id,name,created_at,settings) "
            f"VALUES({marker},{marker},{marker},CURRENT_TIMESTAMP,{marker})",
            (_SITE_ID, project_id, _SITE_NAME, "{}"),
        )
        return
    owner = int(row["project_id"] if hasattr(row, "keys") else row[0])
    if owner != project_id:
        raise RuntimeError(
            f"hosted QA site {_SITE_ID!r} belongs to project {owner}, "
            f"not yoke project {project_id}"
        )


def _runtime_environment_rows(conn: Any, *, runtime: str) -> list[Any]:
    rows = conn.execute(
        "SELECT id,site,name FROM environments WHERE site=%s ORDER BY id"
        if db_backend.connection_is_postgres(conn)
        else "SELECT id,site,name FROM environments WHERE site=? ORDER BY id",
        (_SITE_ID,),
    ).fetchall()
    return [
        row
        for row in rows
        if str(row["name"] if hasattr(row, "keys") else row[2]).lower()
        in _ALIASES[runtime]
    ]


def _ensure_environment(conn: Any, *, runtime: str) -> None:
    matches = _runtime_environment_rows(conn, runtime=runtime)
    if len(matches) == 1:
        return
    if len(matches) > 1:
        raise RuntimeError(
            f"hosted QA site {_SITE_ID!r} has multiple {runtime!r} environments"
        )
    marker = _p(conn)
    environment_id = f"{_SITE_ID}-{runtime}"
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
        (environment_id, _SITE_ID, runtime, "{}"),
    )


def apply(conn: Any) -> None:
    """Ensure every hosted Yoke tenant declares its own runtime target."""
    missing = [
        table
        for table in ("projects", "sites", "environments")
        if not _table_exists(conn, table)
    ]
    if missing:
        raise RuntimeError(
            "hosted QA runtime environment requires deployed tables: "
            + ", ".join(missing)
        )
    runtime = _runtime()
    project_id = _yoke_project_id(conn)
    _ensure_site(conn, project_id=project_id)
    _ensure_environment(conn, runtime=runtime)


def invariants(conn: Any) -> None:
    """Require one runtime-compatible environment owned by the Yoke project."""
    runtime = _runtime()
    project_id = _yoke_project_id(conn)
    marker = _p(conn)
    site = conn.execute(
        f"SELECT project_id FROM sites WHERE id={marker}",
        (_SITE_ID,),
    ).fetchone()
    if site is None:
        raise AssertionError(f"hosted QA site {_SITE_ID!r} is absent")
    owner = int(site["project_id"] if hasattr(site, "keys") else site[0])
    if owner != project_id:
        raise AssertionError(
            f"hosted QA site {_SITE_ID!r} does not belong to the yoke project"
        )
    if len(_runtime_environment_rows(conn, runtime=runtime)) != 1:
        raise AssertionError(
            f"hosted QA site {_SITE_ID!r} does not have one {runtime!r} environment"
        )


__all__ = ["MIGRATION_NAME", "apply", "invariants"]
