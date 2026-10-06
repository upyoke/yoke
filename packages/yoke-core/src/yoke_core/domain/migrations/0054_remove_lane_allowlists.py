"""Remove execution-lane action permissions while preserving lane groupings."""

from __future__ import annotations

from typing import Any

from yoke_contracts.session_lane import lane_presentation, retired_lane_setting_keys
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
        if not isinstance(settings.get("lane_metadata", {}), dict):
            raise ValueError("lane_metadata must be an object")
        return settings
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"session_routing_document_invalid: capability {row[0]} cannot "
            "converge. Recovery: repair its session-routing settings to a "
            "JSON object through yoke projects capability-settings, then "
            "retry rehearsal or boot."
        ) from exc


def _converged(settings: dict[str, Any]) -> dict[str, Any]:
    keys = retired_lane_setting_keys(settings)
    if not keys:
        return settings
    metadata = dict(settings.get("lane_metadata") or {})
    for key in keys:
        value = settings[key]
        lanes = value if isinstance(value, dict) else ()
        if not isinstance(value, dict):
            lanes = key.split("_", 2)[2:]
        for lane in lanes:
            lane_id = str(lane).strip().upper()
            if lane_id:
                presentation = lane_presentation(lane_id, settings)
                if not presentation["glyph"]:
                    presentation.pop("glyph")
                metadata.setdefault(lane_id, presentation)
    result = {key: value for key, value in settings.items() if key not in keys}
    if metadata:
        result["lane_metadata"] = metadata
    return result


def apply(conn: Any) -> None:
    marker = "%s" if connection_is_postgres(conn) else "?"
    for row in _rows(conn):
        settings = _settings(row)
        converged = _converged(settings)
        if converged != settings:
            conn.execute(
                f"UPDATE project_capabilities SET settings = {marker} WHERE id = {marker}",
                (json_helper.dumps_compact(converged), int(row[0])),
            )


def invariants(conn: Any) -> None:
    for row in _rows(conn):
        if retired_lane_setting_keys(_settings(row)):
            raise AssertionError(
                f"lane_action_allowlists_remain: capability {row[0]}. "
                "Recovery: rehearse the remove-lane-allowlists migration."
            )
