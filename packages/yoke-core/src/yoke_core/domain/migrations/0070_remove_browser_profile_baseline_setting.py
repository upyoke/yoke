"""Remove the sealed browser-profile baseline path from Test Machine settings.

Browser sign-ins on a Test Machine are kept live in the host's identity store
and preserved through a reset; a sealed copy of a profile is never restored,
because sites rotate session cookies and a restored copy is stale. Stored
``browser_profile_baseline_path`` values therefore name nothing any build
reads, and the settings validator no longer accepts the key. Every other
setting is kept exactly as stored.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain import json_helper
from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE
RETIRED_SETTING = "browser_profile_baseline_path"


def _rows(conn: Any) -> list[Any]:
    if not _table_exists(conn, "project_capabilities"):
        return []
    marker = "%s" if connection_is_postgres(conn) else "?"
    return conn.execute(
        "SELECT id, settings FROM project_capabilities "
        f"WHERE type LIKE {marker} ORDER BY id",
        ("test-machine:%",),
    ).fetchall()


def _settings(row: Any) -> dict[str, Any]:
    try:
        settings = json_helper.loads_text(str(row[1] or "{}"))
        if not isinstance(settings, dict):
            raise ValueError("settings must be an object")
        return settings
    except (ValueError, TypeError) as exc:
        raise RuntimeError(
            f"test_machine_settings_invalid: capability {row[0]} cannot "
            "converge. Recovery: repair its test-machine settings to a JSON "
            "object through yoke projects capability-settings, then retry "
            "rehearsal or boot."
        ) from exc


def apply(conn: Any) -> None:
    marker = "%s" if connection_is_postgres(conn) else "?"
    for row in _rows(conn):
        settings = _settings(row)
        if RETIRED_SETTING not in settings:
            continue
        converged = {
            key: value for key, value in settings.items() if key != RETIRED_SETTING
        }
        conn.execute(
            f"UPDATE project_capabilities SET settings = {marker} WHERE id = {marker}",
            (json_helper.dumps_compact(converged), int(row[0])),
        )


def invariants(conn: Any) -> None:
    for row in _rows(conn):
        if RETIRED_SETTING in _settings(row):
            raise AssertionError(
                f"browser_profile_baseline_setting_remains: capability {row[0]}. "
                "Recovery: rehearse the remove-browser-profile-baseline-setting "
                "migration."
            )
