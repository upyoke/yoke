"""Resolve and stamp first-class environment delivery records.

Run ``target_env`` values are free text on the run row. Once a project
registers environment rows, create-time validation requires the token to
be a registered name, id, or an existing flow ``target_env`` for that
project. Successful completion writes ``environments.last_deployed_at``.
"""

from __future__ import annotations

from typing import Any, Iterable, Optional

from yoke_core.domain.db_helpers import iso8601_now, query_rows, query_scalar


DELIVERY_ENV_NAMES = frozenset({"prod", "stage"})
UNBOUND_TARGET_ENVS = frozenset({"", "ephemeral"})


class UnregisteredTargetEnv(ValueError):
    """``target_env`` is not in the project's registered delivery set."""


def require_delivery_env_name(name: str) -> str:
    """Return a closed delivery name, or raise ``ValueError``."""
    normalized = str(name or "").strip()
    if normalized not in DELIVERY_ENV_NAMES:
        raise ValueError(
            "environment name must be prod or stage; "
            f"got {normalized!r}"
        )
    return normalized


def registered_target_env_tokens(conn: Any, project_id: int) -> list[str]:
    """Return the sorted delivery tokens a project currently recognizes."""
    tokens: set[str] = set()
    for row in query_rows(
        conn,
        "SELECT e.id, e.name FROM environments e "
        "JOIN sites s ON s.id = e.site WHERE s.project_id = %s",
        (project_id,),
    ):
        tokens.update(_nonempty_tokens((
            _row_value(row, "id", 0), _row_value(row, "name", 1),
        )))
    for row in query_rows(
        conn,
        "SELECT target_env FROM deployment_flows WHERE project_id = %s",
        (project_id,),
    ):
        tokens.update(_nonempty_tokens((_row_value(row, "target_env", 0),)))
    return sorted(tokens)


def require_registered_target_env(
    conn: Any,
    project_id: int,
    target_env: Optional[str],
) -> None:
    """Refuse a named target that is not in the project's registered set.

    Projects with no environment rows stay unconstrained so onboarding and
    tests can create runs before a registry exists. Empty and ``ephemeral``
    targets are preview/internal lanes, not missing delivery records.
    """
    token = str(target_env or "").strip()
    if token.lower() in UNBOUND_TARGET_ENVS:
        return
    env_count = query_scalar(
        conn,
        "SELECT COUNT(*) FROM environments e "
        "JOIN sites s ON s.id = e.site WHERE s.project_id = %s",
        (project_id,),
    )
    if not env_count:
        return
    allowed = registered_target_env_tokens(conn, project_id)
    if token not in allowed:
        raise UnregisteredTargetEnv(
            f"target_env {token!r} is not registered; "
            f"registered: {', '.join(allowed)}"
        )


def resolve_environment_id(
    conn: Any,
    project_id: int,
    target_env: Optional[str],
) -> Optional[str]:
    """Return the project environment id for ``target_env``, if any."""
    token = str(target_env or "").strip()
    if not token:
        return None
    row = query_scalar(
        conn,
        "SELECT e.id FROM environments e JOIN sites s ON s.id = e.site "
        "WHERE s.project_id = %s AND e.id = %s",
        (project_id, token),
    )
    if row:
        return str(row)
    return query_scalar(
        conn,
        "SELECT e.id FROM environments e JOIN sites s ON s.id = e.site "
        "WHERE s.project_id = %s AND e.name = %s",
        (project_id, token),
    )


def stamp_environment_last_deployed(
    conn: Any,
    environment_id: str,
    *,
    when: Optional[str] = None,
) -> None:
    """Write ``last_deployed_at`` on one environment row."""
    conn.execute(
        "UPDATE environments SET last_deployed_at = %s WHERE id = %s",
        (when or iso8601_now(), environment_id),
    )


def stamp_run_environment(
    conn: Any,
    run_id: str,
    *,
    when: Optional[str] = None,
) -> Optional[str]:
    """Stamp the run's resolved environment; return the id or ``None``."""
    row = query_rows(
        conn,
        "SELECT project_id, target_env FROM deployment_runs WHERE id = %s",
        (run_id,),
    )
    if not row:
        return None
    environment_id = resolve_environment_id(
        conn,
        int(_row_value(row[0], "project_id", 0)),
        _row_value(row[0], "target_env", 1),
    )
    if environment_id is None:
        return None
    stamp_environment_last_deployed(conn, environment_id, when=when)
    return environment_id


def _row_value(row: Any, key: str, index: int) -> Any:
    if hasattr(row, "keys"):
        return row[key]
    return row[index]


def _nonempty_tokens(values: Iterable[Any]) -> list[str]:
    return [str(value).strip() for value in values if str(value or "").strip()]


__all__ = [
    "DELIVERY_ENV_NAMES",
    "UNBOUND_TARGET_ENVS",
    "UnregisteredTargetEnv",
    "registered_target_env_tokens",
    "require_delivery_env_name",
    "require_registered_target_env",
    "resolve_environment_id",
    "stamp_environment_last_deployed",
    "stamp_run_environment",
]
