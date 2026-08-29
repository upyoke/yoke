"""Ephemeral environments domain logic (invoked via ``python3 -m yoke_core.domain.ephemeral_env``).

Manages the ``ephemeral_environments`` table: create, update, query,
and cleanup of ephemeral environments for deployment testing.

CLI usage::

    python3 -m yoke_core.domain.ephemeral_env <subcmd> [args...]

Exit codes: 0 success, 1 error/not-found, 2 usage error.
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain.db_helpers import (
    iso8601_now,
    query_one,
    query_rows,
    query_scalar,
)
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.ephemeral_environment_item_binding import (
    INACTIVE_ENVIRONMENT_STATUSES,
    prepare_create_item_binding,
    prepare_update_item_binding,
)
from yoke_core.domain.workflow_item_binding_lock import (
    rollback_workflow_binding_write_errors,
)

_SELECT_COLS = (
    "ee.id, p.slug AS project, ee.branch, ee.item, ee.workflow_run_id, "
    "ee.github_ref, ee.port_api, ee.port_web, ee.url, ee.status, "
    "ee.started_at, ee.stopped_at, ee.health_check_url, ee.deployed_sha, "
    "ee.created_at"
)

EPHEMERAL_ENV_FIELDS = (
    "id",
    "project",
    "branch",
    "item",
    "workflow_run_id",
    "github_ref",
    "port_api",
    "port_web",
    "url",
    "status",
    "started_at",
    "stopped_at",
    "health_check_url",
    "deployed_sha",
    "created_at",
)

_UPDATE_FIELDS = frozenset(
    {
        "status",
        "branch",
        "item",
        "workflow_run_id",
        "github_ref",
        "port_api",
        "port_web",
        "url",
        "started_at",
        "stopped_at",
        "health_check_url",
        "deployed_sha",
    }
)

_GET_FIELDS = frozenset(
    {
        "id",
        "project",
        "branch",
        "item",
        "workflow_run_id",
        "github_ref",
        "port_api",
        "port_web",
        "url",
        "status",
        "started_at",
        "stopped_at",
        "health_check_url",
        "deployed_sha",
        "created_at",
    }
)


def _format_row(row) -> str:
    return "|".join("" if v is None else str(v) for v in tuple(row))


@rollback_workflow_binding_write_errors
def cmd_create(
    conn,
    project: str,
    branch: str,
    item: str = "",
    workflow_run_id: str = "",
    github_ref: str = "",
) -> str:
    now = iso8601_now()
    project_id = resolve_project_id(conn, project)
    item = prepare_create_item_binding(
        conn,
        public_ref=item,
        project=project,
        branch=branch,
    )
    conn.execute(
        "INSERT INTO ephemeral_environments "
        "(project_id, branch, item, workflow_run_id, github_ref, status, "
        " started_at, created_at) "
        "VALUES (%s, %s, %s, %s, %s, 'pending', %s, %s) "
        "ON CONFLICT(project_id, branch) DO UPDATE SET "
        "item=excluded.item, workflow_run_id=excluded.workflow_run_id, "
        "github_ref=excluded.github_ref, status='pending', "
        "started_at=%s, stopped_at=NULL",
        (project_id, branch, item, workflow_run_id, github_ref, now, now, now),
    )
    conn.commit()
    row_id = query_scalar(
        conn,
        "SELECT id FROM ephemeral_environments WHERE project_id=%s AND branch=%s",
        (project_id, branch),
    )
    return str(row_id)


@rollback_workflow_binding_write_errors
def cmd_update(conn, env_id: int, field: str, value: str) -> str:
    if field not in _UPDATE_FIELDS:
        raise ValueError(
            f"unknown field '{field}'. Valid fields: {' '.join(sorted(_UPDATE_FIELDS))}"
        )

    value = prepare_update_item_binding(
        conn,
        env_id=int(env_id),
        field=field,
        value=value,
    )

    # Auto-set stopped_at for terminal statuses
    if field == "status" and value in INACTIVE_ENVIRONMENT_STATUSES:
        conn.execute(
            f"UPDATE ephemeral_environments SET {field}=%s, stopped_at=%s WHERE id=%s",
            (value, iso8601_now(), env_id),
        )
        conn.commit()
        return f"Updated env {env_id}: {field}={value} (stopped_at auto-set)"

    conn.execute(
        f"UPDATE ephemeral_environments SET {field}=%s WHERE id=%s",
        (value, env_id),
    )
    conn.commit()
    return f"Updated env {env_id}: {field}={value}"


def cmd_get(conn, project: str, branch: str) -> str:
    project_id = resolve_project_id(conn, project)
    row = query_one(
        conn,
        f"SELECT {_SELECT_COLS} FROM ephemeral_environments ee "
        "JOIN projects p ON p.id = ee.project_id "
        "WHERE ee.project_id=%s AND ee.branch=%s",
        (project_id, branch),
    )
    if row is None:
        raise LookupError(f"no env found for project='{project}' branch='{branch}'")
    return _format_row(row)


def cmd_get_by_id(conn, env_id: int, field: Optional[str] = None) -> str:
    if field:
        if field not in _GET_FIELDS:
            raise ValueError(f"invalid field '{field}'")
        exists = query_scalar(
            conn, "SELECT COUNT(*) FROM ephemeral_environments WHERE id=%s", (env_id,)
        )
        if not exists:
            raise LookupError(f"ephemeral environment '{env_id}' not found")
        if field == "project":
            val = query_scalar(
                conn,
                "SELECT p.slug FROM ephemeral_environments ee "
                "JOIN projects p ON p.id = ee.project_id WHERE ee.id=%s",
                (env_id,),
            )
        else:
            val = query_scalar(
                conn,
                f"SELECT {field} FROM ephemeral_environments WHERE id=%s",
                (env_id,),
            )
        return "" if val is None else str(val)
    else:
        row = query_one(
            conn,
            f"SELECT {_SELECT_COLS} FROM ephemeral_environments ee "
            "JOIN projects p ON p.id = ee.project_id WHERE ee.id=%s",
            (env_id,),
        )
        if row is None:
            raise LookupError(f"ephemeral environment '{env_id}' not found")
        return _format_row(row)


def cmd_list(conn, project: Optional[str] = None, status: Optional[str] = None) -> str:
    conditions: list[str] = []
    params: list = []
    if project:
        conditions.append("ee.project_id=%s")
        params.append(resolve_project_id(conn, project))
    if status:
        conditions.append("ee.status=%s")
        params.append(status)

    where = f"WHERE {' AND '.join(conditions)}" if conditions else ""
    rows = query_rows(
        conn,
        f"SELECT {_SELECT_COLS} FROM ephemeral_environments ee "
        f"JOIN projects p ON p.id = ee.project_id {where} ORDER BY ee.id ASC",
        tuple(params),
    )
    return "\n".join(_format_row(row) for row in rows)


def cmd_cleanup(conn, max_age_hours: int = 24) -> str:
    # Compute the cutoff in Python so cleanup does not depend on SQL date
    # modifier dialect.
    from datetime import datetime, timedelta, timezone

    cutoff = (datetime.now(timezone.utc) - timedelta(hours=max_age_hours)).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    count = query_scalar(
        conn,
        "SELECT COUNT(*) FROM ephemeral_environments "
        "WHERE status NOT IN ('stopped', 'failed') "
        "AND created_at < %s",
        (cutoff,),
    )
    if count and count > 0:
        conn.execute(
            "UPDATE ephemeral_environments "
            "SET status='stopped', stopped_at=%s "
            "WHERE status NOT IN ('stopped', 'failed') "
            "AND created_at < %s",
            (iso8601_now(), cutoff),
        )
        conn.commit()
    return str(count or 0)


def main(argv: Optional[list[str]] = None) -> None:
    from yoke_core.domain.ephemeral_env_cli import main as cli_main

    cli_main(argv)


if __name__ == "__main__":
    main()
