"""Remove product fleet tuning from organization settings, preserving membership."""

from typing import Any

from yoke_core.domain import json_helper
from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE


def _rows(conn: Any) -> list[Any]:
    if not _table_exists(conn, "organizations"):
        return []
    return conn.execute("SELECT id,settings FROM organizations ORDER BY id").fetchall()


def _document(row: Any) -> dict[str, Any]:
    try:
        value = json_helper.loads_text(str(row[1] or "{}"))
        if not isinstance(value, dict):
            raise ValueError("settings must be an object")
        return value
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"organization_settings_invalid: organization {row[0]}. Recovery: "
            "repair its settings to a JSON object, then retry boot or rehearsal."
        ) from exc


def apply(conn: Any) -> None:
    marker = "%s" if connection_is_postgres(conn) else "?"
    for row in _rows(conn):
        document = _document(row)
        removed = [
            key for key in document if key == "fleet" or key.startswith("fleet.")
        ]
        if removed:
            for key in removed:
                document.pop(key)
            conn.execute(
                f"UPDATE organizations SET settings={marker} WHERE id={marker}",
                (json_helper.dumps_compact(document), int(row[0])),
            )


def invariants(conn: Any) -> None:
    for row in _rows(conn):
        if any(key == "fleet" or key.startswith("fleet.") for key in _document(row)):
            raise AssertionError(
                f"fleet_settings_remain: organization {row[0]}. Recovery: "
                "rehearse the remove-fleet-settings migration."
            )
