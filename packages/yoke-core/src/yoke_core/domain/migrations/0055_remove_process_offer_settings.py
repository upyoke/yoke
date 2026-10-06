"""Remove unused process-offer policy from stored session-routing documents.

Process staffing is explicit. Keep lane groupings and every unrelated setting;
the serving floor prevents an older writer restoring the removed policy.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_lane import retired_process_offer_keys
from yoke_core.domain import json_helper
from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE


def _rows(conn: Any) -> list[Any]:
    if not _table_exists(conn, "project_capabilities"):
        return []
    marker = "%s" if connection_is_postgres(conn) else "?"
    return conn.execute(
        "SELECT id, settings FROM project_capabilities "
        f"WHERE type = {marker} ORDER BY id",
        ("session-routing",),
    ).fetchall()


def _settings(row: Any) -> dict[str, Any]:
    try:
        settings = json_helper.loads_text(str(row[1] or "{}"))
        if not isinstance(settings, dict):
            raise ValueError("settings must be an object")
        return settings
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"session_routing_document_invalid: capability {row[0]} cannot "
            "converge. Recovery: repair its session-routing settings to a "
            "JSON object through yoke projects capability-settings, then "
            "retry rehearsal or boot."
        ) from exc


def apply(conn: Any) -> None:
    marker = "%s" if connection_is_postgres(conn) else "?"
    for row in _rows(conn):
        settings = _settings(row)
        retired = retired_process_offer_keys(settings)
        if retired:
            converged = {
                key: value for key, value in settings.items() if key not in retired
            }
            conn.execute(
                f"UPDATE project_capabilities SET settings = {marker} WHERE id = {marker}",
                (json_helper.dumps_compact(converged), int(row[0])),
            )


def invariants(conn: Any) -> None:
    for row in _rows(conn):
        if retired_process_offer_keys(_settings(row)):
            raise AssertionError(
                f"process_offer_policy_remains: capability {row[0]}. "
                "Recovery: rehearse the remove-process-offer-settings migration."
            )
