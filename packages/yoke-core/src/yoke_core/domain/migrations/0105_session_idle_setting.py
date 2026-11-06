"""Preserve project idle thresholds under their shared session-state name."""

from typing import Any

from yoke_core.domain import json_helper
from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE
OLD_KEY = "steering_report_idle_minutes"
NEW_KEY = "session_idle_minutes"


def _rows(conn: Any) -> list[Any]:
    if not _table_exists(conn, "project_capabilities"):
        return []
    return conn.execute(
        "SELECT id,settings FROM project_capabilities WHERE type='project-policy' ORDER BY id"
    ).fetchall()


def _document(row: Any) -> dict[str, Any]:
    try:
        value = json_helper.loads_text(str(row[1] or "{}"))
        if isinstance(value, dict):
            return value
    except (ValueError, TypeError):
        pass
    raise RuntimeError(
        f"session_idle_settings_invalid: capability {row[0]}. Recovery: repair "
        "its project-policy settings to a JSON object, then retry boot or rehearsal."
    )


def apply(conn: Any) -> None:
    marker = "%s" if connection_is_postgres(conn) else "?"
    for row in _rows(conn):
        document = _document(row)
        if OLD_KEY not in document:
            continue
        # The already-present destination is authoritative on a repeated or
        # partially converged document; remove only the retired spelling.
        document.setdefault(NEW_KEY, document[OLD_KEY])
        document.pop(OLD_KEY)
        conn.execute(
            f"UPDATE project_capabilities SET settings={marker} WHERE id={marker}",
            (json_helper.dumps_compact(document), int(row[0])),
        )


def invariants(conn: Any) -> None:
    for row in _rows(conn):
        if OLD_KEY in _document(row):
            raise RuntimeError(
                f"session_idle_settings_not_converged: capability {row[0]}. "
                "Recovery: rehearse the session idle settings migration and retry boot."
            )
