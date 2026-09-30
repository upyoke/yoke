"""Converge persistent SSH Test Machine settings to a declared operating system."""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.machine_config.test_machine import validate_test_machine_settings
from yoke_core.domain.db_backend import connection_is_postgres
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE


def _settings(raw: Any, capability: str) -> dict[str, str]:
    try:
        value = json.loads(str(raw or "{}"))
        if not isinstance(value, dict):
            raise ValueError("settings must be an object")
        legacy = value.pop("host_kind", None)
        if legacy not in (None, "mac-ssh"):
            raise ValueError("legacy SSH Test Machine kind is unsupported")
        value.setdefault("os", "macos")
        settings = validate_test_machine_settings(value)
        if capability != "test-machine:" + settings["resource_name"]:
            raise ValueError("resource name disagrees with capability type")
        return settings
    except (TypeError, ValueError) as exc:
        raise AssertionError(
            f"test_machine_os_convergence_refused: {capability}: {exc}; "
            "repair the stored Test Machine settings through the registered "
            "settings replacement surface before rehearsing again"
        ) from exc


def _rows(conn: Any):
    marker = "%s" if connection_is_postgres(conn) else "?"
    return conn.execute(
        "SELECT id, type, settings FROM project_capabilities "
        f"WHERE type LIKE {marker} ORDER BY id",
        ("test-machine:%",),
    ).fetchall()


def apply(conn: Any) -> None:
    if not _table_exists(conn, "project_capabilities"):
        return
    marker = "%s" if connection_is_postgres(conn) else "?"
    # Validate the complete touch set before the first write. The boot owner
    # commits this rewrite and its ledger membership in one transaction.
    updates = [
        (
            json.dumps(
                _settings(row[2], str(row[1])), separators=(",", ":"), sort_keys=True
            ),
            int(row[0]),
        )
        for row in _rows(conn)
    ]
    for settings, row_id in updates:
        conn.execute(
            f"UPDATE project_capabilities SET settings = {marker} WHERE id = {marker}",
            (settings, row_id),
        )


def invariants(conn: Any) -> None:
    if not _table_exists(conn, "project_capabilities"):
        return
    for row in _rows(conn):
        value = json.loads(str(row[2]))
        if "host_kind" in value or "os" not in value:
            raise AssertionError(
                "test_machine_os_not_converged: rehearse the OS settings migration"
            )
        _settings(row[2], str(row[1]))
