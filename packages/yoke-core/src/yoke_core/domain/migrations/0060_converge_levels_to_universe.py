"""Converge per-project level routing into the universe levels.

Execution levels became ordered lists of launchable options held once per
universe, with a project ``session-routing`` document carrying only an
optional ``levels`` override. Every project used to receive its own copy of
the harness defaults (declared level metadata, selector rules, and
executor defaults), which no reader consults any more. This entry keeps only
``levels`` in every stored document and deletes a document left empty, so
each project reads the universe levels unless it holds a real override and
every stored document satisfies the write contract, which accepts no other
key.

The serving floor keeps an older build, which seeds the retired keys into
every project, from writing them back.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import json_helper
from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE
ROUTING_CAPABILITY = "session-routing"
KEPT_KEY = "levels"


def _retired(settings: dict[str, Any]) -> list[str]:
    return sorted(str(key) for key in settings if key != KEPT_KEY)


def converged(settings: dict[str, Any]) -> dict[str, Any]:
    """Return the document this entry stores; empty means the row is deleted."""
    return {key: value for key, value in settings.items() if key == KEPT_KEY}


def _rows(conn: Any) -> list[Any]:
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


def apply(conn: Any) -> None:
    marker = "%s" if connection_is_postgres(conn) else "?"
    for row in _rows(conn):
        settings = _settings(row)
        kept = converged(settings)
        if kept == settings and kept:
            continue
        if kept:
            conn.execute(
                f"UPDATE project_capabilities SET settings = {marker} "
                f"WHERE id = {marker}",
                (json_helper.dumps_compact(kept), int(row[0])),
            )
        else:
            conn.execute(
                f"DELETE FROM project_capabilities WHERE id = {marker}",
                (int(row[0]),),
            )


def invariants(conn: Any) -> None:
    """Prove every stored document carries only its levels override."""
    for row in _rows(conn):
        settings = _settings(row)
        retired = _retired(settings)
        assert settings and not retired, (
            f"session-routing capability {row[0]} carries no levels override "
            f"or keys other than levels: {', '.join(retired) or '(empty)'}"
        )


__all__ = ["MINIMUM_SERVING_VERSION", "apply", "converged", "invariants"]
