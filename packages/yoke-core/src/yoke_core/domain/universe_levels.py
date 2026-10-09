"""Universe-wide execution levels and the per-project override.

The universe definition lives in ``universe_settings`` under the ``levels``
key: one row per universe, written only by an explicit operator command. An
absent row means the universe reads the shipped scheme
(:data:`yoke_contracts.level_defaults.DEFAULT_LEVELS`), so a shipped change
reaches every universe that never customized its levels. A project may
override the universe definition with a ``levels`` document in its
``session-routing`` capability; readers take the override when present.
"""

from __future__ import annotations

from yoke_contracts.timestamps import utc_now
from yoke_core.domain.db_helpers import instant_parameter
from typing import Any, Optional

from yoke_contracts.levels import (
    LEVELS_KEY,
    Level,
    levels_payload,
    parse_levels,
    resolve_effective_levels,
)
from yoke_contracts.project_contract.project_keys import SESSION_ROUTING_CAPABILITY
from yoke_core.domain import db_backend, json_helper
from yoke_core.domain.schema_init_apply import execute_schema_script

TABLE = "universe_settings"


class UniverseLevelsError(ValueError):
    """A stored levels document cannot be read; names the repair."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(f"{code}: {message}")
        self.code = code


def create_universe_settings_table(conn: Any) -> None:
    """Add the universe settings store without changing any existing table."""
    execute_schema_script(
        conn,
        f"""
        CREATE TABLE IF NOT EXISTS {TABLE} (
          key TEXT PRIMARY KEY,
          value TEXT NOT NULL,
          updated_at TIMESTAMPTZ NOT NULL,
          updated_by_actor_id INTEGER
        );
        """,
    )


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _loads(raw: Any, *, where: str, repair: str) -> Any:
    try:
        return json_helper.loads_text(str(raw))
    except (TypeError, ValueError) as exc:
        raise UniverseLevelsError(
            "levels_document_unreadable",
            f"{where} is not valid JSON. Recovery: {repair}",
        ) from exc


def stored_universe_levels(conn: Any) -> Any:
    """Return the stored universe document, or ``None`` when none is stored."""
    row = conn.execute(
        f"SELECT value FROM {TABLE} WHERE key = {_p(conn)}", (LEVELS_KEY,)
    ).fetchone()
    if row is None:
        return None
    return _loads(
        row[0],
        where="the stored universe levels",
        repair="store a valid document with `yoke universe levels set`.",
    )


def project_routing_settings(conn: Any, project_id: Optional[int]) -> Optional[dict]:
    """Return the project's ``session-routing`` document, or ``None``."""
    if project_id is None:
        return None
    row = conn.execute(
        "SELECT settings FROM project_capabilities "
        f"WHERE project_id = {_p(conn)} AND type = {_p(conn)}",
        (int(project_id), SESSION_ROUTING_CAPABILITY),
    ).fetchone()
    if row is None:
        return None
    settings = _loads(
        row[0] or "{}",
        where=f"project {project_id}'s session-routing settings",
        repair=(
            "rewrite them with `yoke projects capability-settings set "
            "--cap-type session-routing`."
        ),
    )
    return settings if isinstance(settings, dict) else None


def effective_levels(
    conn: Any, project_id: Optional[int]
) -> tuple[tuple[Level, ...], str]:
    """Return the levels a project reads and their source.

    Source is ``project`` (its override), ``universe`` (the stored universe
    definition), or ``default`` (the shipped scheme).
    """
    return resolve_effective_levels(
        project_routing_settings(conn, project_id), stored_universe_levels(conn)
    )


def write_universe_levels(
    conn: Any, raw: Any, *, actor_id: Optional[int]
) -> tuple[Level, ...]:
    """Validate and store the universe levels document, replacing any prior one."""
    levels = parse_levels(raw)
    marker = _p(conn)
    now = instant_parameter(conn, utc_now())
    conn.execute(
        f"INSERT INTO {TABLE} (key, value, updated_at, updated_by_actor_id) "
        f"VALUES ({marker}, {marker}, {marker}, {marker}) "
        "ON CONFLICT (key) DO UPDATE SET value = excluded.value, "
        "updated_at = excluded.updated_at, "
        "updated_by_actor_id = excluded.updated_by_actor_id",
        (LEVELS_KEY, json_helper.dumps_compact(levels_payload(levels)), now, actor_id),
    )
    conn.commit()
    return levels


__all__ = [
    "TABLE",
    "UniverseLevelsError",
    "create_universe_settings_table",
    "effective_levels",
    "project_routing_settings",
    "stored_universe_levels",
    "write_universe_levels",
]
