"""Rename execution lanes to execution levels in sessions and routing policy.

Two stored surfaces carried the retired name: the ``harness_sessions``
column every session row stamps, and the ``session-routing`` capability
documents that declare and route to levels. Both converge here so no reader
has to recognize either spelling.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_level import renamed_routing_keys
from yoke_core.domain import json_helper
from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists


MINIMUM_SERVING_VERSION = NEXT_RELEASE
TABLE = "harness_sessions"
RETIRED_COLUMN = "execution_lane"
CURRENT_COLUMN = "execution_level"
RETIRED_INDEX = "idx_harness_sessions_lane"
CURRENT_INDEX = "idx_harness_sessions_level"
ROUTING_CAPABILITY = "session-routing"


def _rename_column(conn: Any) -> None:
    """Preserve every stamped level while converging either pre-boot shape."""
    if not _table_exists(conn, TABLE) or not _column_exists(
        conn, TABLE, RETIRED_COLUMN
    ):
        return
    conn.execute(f'DROP INDEX IF EXISTS "{RETIRED_INDEX}"')
    if _column_exists(conn, TABLE, CURRENT_COLUMN):
        conn.execute(
            f'UPDATE "{TABLE}" SET "{CURRENT_COLUMN}" = "{RETIRED_COLUMN}" '
            f'WHERE "{RETIRED_COLUMN}" IS NOT NULL'
        )
        conn.execute(f'ALTER TABLE "{TABLE}" DROP COLUMN "{RETIRED_COLUMN}"')
    else:
        conn.execute(
            f'ALTER TABLE "{TABLE}" RENAME COLUMN "{RETIRED_COLUMN}" '
            f'TO "{CURRENT_COLUMN}"'
        )
    conn.execute(
        f'CREATE INDEX IF NOT EXISTS "{CURRENT_INDEX}" ON "{TABLE}"("{CURRENT_COLUMN}")'
    )


def _routing_rows(conn: Any) -> list[Any]:
    if not _table_exists(conn, "project_capabilities"):
        return []
    marker = "%s" if connection_is_postgres(conn) else "?"
    return conn.execute(
        "SELECT id, settings FROM project_capabilities "
        f"WHERE type = {marker} ORDER BY id",
        (ROUTING_CAPABILITY,),
    ).fetchall()


def _settings(row: Any) -> dict[str, Any]:
    try:
        settings = json_helper.loads_text(str(row[1] or "{}"))
    except (ValueError, TypeError) as exc:
        settings = exc
    if not isinstance(settings, dict):
        raise RuntimeError(
            f"session_routing_document_invalid: capability {row[0]} cannot "
            "converge. Recovery: repair its session-routing settings to a "
            "JSON object through yoke projects capability-settings, then "
            "retry rehearsal or boot."
        )
    return settings


def _converged(capability_id: Any, settings: dict[str, Any]) -> dict[str, Any]:
    renamed = renamed_routing_keys(settings)
    clashes = sorted(new for new in renamed.values() if new in settings)
    if clashes:
        raise RuntimeError(
            f"session_routing_level_keys_conflict: capability {capability_id} "
            f"carries both a retired lane key and its replacement "
            f"({', '.join(clashes)}). Recovery: keep one spelling through "
            "yoke projects capability-settings, then retry rehearsal or boot."
        )
    converged = {renamed.get(key, key): value for key, value in settings.items()}
    rules = converged.get("level_rules")
    if isinstance(rules, list):
        converged["level_rules"] = [_converged_rule(rule) for rule in rules]
    return converged


def _converged_rule(rule: Any) -> Any:
    """Rename one selector rule's ``lane`` target to ``level``."""
    if not isinstance(rule, dict) or "lane" not in rule or "level" in rule:
        return rule
    return {("level" if key == "lane" else key): value for key, value in rule.items()}


def _rename_routing_keys(conn: Any) -> None:
    marker = "%s" if connection_is_postgres(conn) else "?"
    for row in _routing_rows(conn):
        settings = _settings(row)
        converged = _converged(row[0], settings)
        if converged != settings:
            conn.execute(
                f"UPDATE project_capabilities SET settings = {marker} "
                f"WHERE id = {marker}",
                (json_helper.dumps_compact(converged), int(row[0])),
            )


def apply(conn: Any) -> None:
    _rename_column(conn)
    _rename_routing_keys(conn)


def invariants(conn: Any) -> None:
    """Prove only the level spellings remain."""
    if _table_exists(conn, TABLE):
        assert _column_exists(conn, TABLE, CURRENT_COLUMN), (
            f"{TABLE}.{CURRENT_COLUMN} is missing after the level rename"
        )
        assert not _column_exists(conn, TABLE, RETIRED_COLUMN), (
            f"{TABLE}.{RETIRED_COLUMN} remains after the level rename"
        )
    for row in _routing_rows(conn):
        settings = _settings(row)
        retired = sorted(renamed_routing_keys(settings))
        rules = settings.get("level_rules")
        if isinstance(rules, list) and any(
            isinstance(rule, dict) and "lane" in rule for rule in rules
        ):
            retired.append("level_rules[].lane")
        assert not retired, (
            f"session-routing capability {row[0]} still carries retired lane "
            f"keys {', '.join(retired)}"
        )


__all__ = [
    "CURRENT_COLUMN",
    "MINIMUM_SERVING_VERSION",
    "RETIRED_COLUMN",
    "TABLE",
    "apply",
    "invariants",
]
