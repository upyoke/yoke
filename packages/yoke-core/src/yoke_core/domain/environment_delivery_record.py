"""Resolve and stamp first-class environment delivery records.

Deployment runs reference their target through the internal numeric
``deployment_runs.target_environment_id``. Operator input is always the
registered environment name; resolution happens here, against the project,
and successful completion writes
``environments.last_deployed_at``.
"""

from __future__ import annotations

from typing import Any, Optional

from yoke_core.domain.db_helpers import iso8601_now, query_rows, query_scalar
from yoke_core.domain.schema_common import _column_exists, _table_exists


PRODUCTION_ENV_NAME = "prod"
STAGE_ENV_NAME = "stage"
DELIVERY_ENV_NAMES = frozenset({PRODUCTION_ENV_NAME, STAGE_ENV_NAME})


class UnregisteredEnvironment(ValueError):
    """The named environment is not registered for the project."""


def require_delivery_env_name(name: str) -> str:
    """Return a closed delivery name, or raise ``ValueError``."""
    normalized = str(name or "").strip()
    if normalized not in DELIVERY_ENV_NAMES:
        raise ValueError(
            "environment name must be prod or stage; "
            f"got {normalized!r}"
        )
    return normalized


def registered_environment_tokens(conn: Any, project_id: int) -> list[str]:
    """Return the sorted environment names a project registers."""
    tokens: set[str] = set()
    if _has_environment_registry(conn):
        for row in query_rows(
            conn,
            "SELECT e.name FROM environments e "
            "JOIN sites s ON s.id = e.site WHERE s.project_id = %s",
            (project_id,),
        ):
            name = str(_row_value(row, "name", 0) or "").strip()
            if name:
                tokens.add(name)
    return sorted(tokens)


def require_registered_environment(
    conn: Any,
    project_id: int,
    environment: Optional[str],
) -> Optional[int]:
    """Resolve *environment* to a registered id, refusing unknown names.

    The referenced environment must be one of the project's rows; numeric
    keys never cross the operator boundary.
    """
    token = str(environment or "").strip()
    if not token:
        return None
    environment_id = resolve_environment_id(conn, project_id, token)
    if environment_id is None:
        allowed = registered_environment_tokens(conn, project_id)
        raise UnregisteredEnvironment(
            f"environment {token!r} is not registered; "
            f"registered: {', '.join(allowed) or '(none)'}"
        )
    return environment_id


def resolve_environment_id(
    conn: Any,
    project_id: int,
    environment: Optional[str],
) -> Optional[int]:
    """Return the project environment id for a registered name, if any."""
    token = str(environment or "").strip()
    if not token or not _has_environment_registry(conn):
        return None
    from yoke_core.domain.environment_reference import (
        EnvironmentReferenceError,
        resolve,
    )
    try:
        return resolve(conn, project_id=project_id, name=token).id
    except EnvironmentReferenceError:
        return None


def environment_name(conn: Any, environment_id: Optional[int]) -> Optional[str]:
    """Return the display name for one environment id, if registered."""
    if environment_id is None or not _table_exists(conn, "environments"):
        return None
    name = query_scalar(
        conn, "SELECT name FROM environments WHERE id = %s", (environment_id,),
    )
    return str(name) if name else None


def stamp_environment_last_deployed(
    conn: Any,
    environment_id: int,
    *,
    when: Optional[str] = None,
) -> None:
    """Write ``last_deployed_at`` on one environment row."""
    if not _column_exists(conn, "environments", "last_deployed_at"):
        return
    conn.execute(
        "UPDATE environments SET last_deployed_at = %s WHERE id = %s",
        (when or iso8601_now(), environment_id),
    )


def stamp_run_environment(
    conn: Any,
    run_id: str,
    *,
    when: Optional[str] = None,
) -> Optional[int]:
    """Stamp the run's referenced environment; return the id or ``None``."""
    row = query_rows(
        conn,
        "SELECT target_environment_id FROM deployment_runs WHERE id = %s",
        (run_id,),
    )
    if not row:
        return None
    environment_id = _row_value(row[0], "target_environment_id", 0)
    if not environment_id or not _table_exists(conn, "environments"):
        return None
    numeric_id = int(environment_id)
    stamp_environment_last_deployed(conn, numeric_id, when=when)
    return numeric_id


def _has_environment_registry(conn: Any) -> bool:
    return _table_exists(conn, "environments") and _table_exists(conn, "sites")


def _row_value(row: Any, key: str, index: int) -> Any:
    if hasattr(row, "keys"):
        return row[key]
    return row[index]


__all__ = [
    "DELIVERY_ENV_NAMES",
    "PRODUCTION_ENV_NAME",
    "STAGE_ENV_NAME",
    "UnregisteredEnvironment",
    "environment_name",
    "registered_environment_tokens",
    "require_delivery_env_name",
    "require_registered_environment",
    "resolve_environment_id",
    "stamp_environment_last_deployed",
    "stamp_run_environment",
]
