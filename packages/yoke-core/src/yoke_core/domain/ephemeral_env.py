"""Ephemeral environments domain logic (invoked via ``python3 -m yoke_core.domain.ephemeral_env``).

Manages the ``ephemeral_environments`` table: create, update, query,
and cleanup of ephemeral environments for deployment testing.

CLI usage::

    python3 -m yoke_core.domain.ephemeral_env <subcmd> [args...]

Exit codes: 0 success, 1 error/not-found, 2 usage error.
"""

from __future__ import annotations

import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import (
    connect,
    iso8601_now,
    query_one,
    query_rows,
    query_scalar,
)
from yoke_core.domain.project_identity import resolve_project_id

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

_USAGE = """\
Usage: ephemeral-env <subcmd> [args...]

Subcommands:
  create <project> <branch> [--item X] [--workflow-run-id Y] [--github-ref Z]
  update <id> <field> <value>
  get <project> <branch>
  get-by-id <id> [field]
  list [--project X] [--status Y]
  cleanup [--max-age-hours N]
"""


def _cli_error(msg: str, code: int = 1) -> None:
    print(msg, file=sys.stderr)
    sys.exit(code)


def _cli_usage_error(msg: str) -> None:
    print(msg, file=sys.stderr)
    sys.exit(2)


def _format_row(row) -> str:
    return "|".join("" if v is None else str(v) for v in tuple(row))


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


def cmd_update(conn, env_id: int, field: str, value: str) -> str:
    if field not in _UPDATE_FIELDS:
        raise ValueError(
            f"unknown field '{field}'. Valid fields: {' '.join(sorted(_UPDATE_FIELDS))}"
        )

    exists = query_scalar(
        conn, "SELECT COUNT(*) FROM ephemeral_environments WHERE id=%s", (env_id,)
    )
    if not exists:
        raise LookupError(f"ephemeral environment '{env_id}' not found")

    # Auto-set stopped_at for terminal statuses
    if field == "status" and value in ("stopped", "failed"):
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
    conditions: List[str] = []
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


def main(argv: Optional[List[str]] = None) -> None:
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        _cli_usage_error(_USAGE)

    subcmd = args[0]
    rest = args[1:]

    conn = connect()

    try:
        if subcmd == "create":
            if len(rest) < 2:
                _cli_usage_error(
                    "Usage: ephemeral-env create <project> <branch> "
                    "[--item X] [--workflow-run-id Y] [--github-ref Z]"
                )
            project = rest[0]
            branch = rest[1]
            item = ""
            workflow_run_id = ""
            github_ref = ""
            i = 2
            while i < len(rest):
                if rest[i] == "--item" and i + 1 < len(rest):
                    item = rest[i + 1]
                    i += 2
                elif rest[i] == "--workflow-run-id" and i + 1 < len(rest):
                    workflow_run_id = rest[i + 1]
                    i += 2
                elif rest[i] == "--github-ref" and i + 1 < len(rest):
                    github_ref = rest[i + 1]
                    i += 2
                else:
                    _cli_error(f"Error: unknown flag '{rest[i]}'", 2)
            print(cmd_create(conn, project, branch, item, workflow_run_id, github_ref))

        elif subcmd == "update":
            if len(rest) < 3:
                _cli_usage_error("Usage: ephemeral-env update <id> <field> <value>")
            print(cmd_update(conn, int(rest[0]), rest[1], rest[2]))

        elif subcmd == "get":
            if len(rest) < 2:
                _cli_usage_error("Usage: ephemeral-env get <project> <branch>")
            print(cmd_get(conn, rest[0], rest[1]))

        elif subcmd == "get-by-id":
            if not rest:
                _cli_usage_error("Usage: ephemeral-env get-by-id <id> [field]")
            field = rest[1] if len(rest) > 1 else None
            print(cmd_get_by_id(conn, int(rest[0]), field))

        elif subcmd == "list":
            project = None
            status = None
            i = 0
            while i < len(rest):
                if rest[i] == "--project" and i + 1 < len(rest):
                    project = rest[i + 1]
                    i += 2
                elif rest[i] == "--status" and i + 1 < len(rest):
                    status = rest[i + 1]
                    i += 2
                else:
                    i += 1
            result = cmd_list(conn, project, status)
            if result:
                print(result)

        elif subcmd == "cleanup":
            max_age = 24
            i = 0
            while i < len(rest):
                if rest[i] == "--max-age-hours" and i + 1 < len(rest):
                    max_age = int(rest[i + 1])
                    i += 2
                else:
                    i += 1
            print(cmd_cleanup(conn, max_age))

        else:
            _cli_usage_error(_USAGE)

    except LookupError as e:
        _cli_error(f"Error: {e}", 1)
    except ValueError as e:
        _cli_error(f"Error: {e}", 2)
    finally:
        conn.close()


if __name__ == "__main__":
    main()
