"""Give each test machine its own capability and verification identity."""

from __future__ import annotations

import json
import re
from typing import Any

from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.schema_common import _column_exists, _table_exists

MINIMUM_SERVING_VERSION = NEXT_RELEASE
BARE_TYPE = "test-machine"
TYPE_PREFIX = BARE_TYPE + ":"
VERIFICATION_TABLE = "test_machine_verifications"
REPLACEMENT_TABLE = "test_machine_verifications_per_capability"
RESOURCE_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,79}$")


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _capability_type(raw_settings: Any) -> str:
    try:
        settings = json.loads(str(raw_settings or "{}"))
    except ValueError as exc:
        raise ValueError(
            "bare test-machine settings are not valid JSON; repair the row "
            "before boot convergence"
        ) from exc
    resource_name = (
        str(settings.get("resource_name") or "").strip()
        if isinstance(settings, dict)
        else ""
    )
    if not RESOURCE_NAME.fullmatch(resource_name):
        raise ValueError(
            "bare test-machine settings have no safe resource_name; repair "
            "the row before boot convergence"
        )
    return TYPE_PREFIX + resource_name


def _rename_capabilities(conn: Any) -> dict[int, str]:
    """Rename bare rows and fold an identical pre-existing target row."""
    if not _table_exists(conn, "project_capabilities"):
        return {}
    marker = _p(conn)
    rows = conn.execute(
        "SELECT project_id,settings,verified_at,created_at "
        f"FROM project_capabilities WHERE type={marker} ORDER BY project_id",
        (BARE_TYPE,),
    ).fetchall()
    renamed: dict[int, str] = {}
    for raw in rows:
        row = dict(raw)
        project_id = int(row["project_id"])
        target = _capability_type(row["settings"])
        existing = conn.execute(
            "SELECT settings,verified_at,created_at FROM project_capabilities "
            f"WHERE project_id={marker} AND type={marker}",
            (project_id, target),
        ).fetchone()
        if existing is None:
            conn.execute(
                "UPDATE project_capabilities SET type="
                f"{marker} WHERE project_id={marker} AND type={marker}",
                (target, project_id, BARE_TYPE),
            )
        else:
            try:
                bare_settings = json.loads(str(row["settings"] or "{}"))
                target_settings = json.loads(str(existing[0] or "{}"))
            except ValueError as exc:
                raise ValueError(
                    f"project {project_id} has an invalid duplicate {target!r} row"
                ) from exc
            if bare_settings != target_settings:
                raise ValueError(
                    f"project {project_id} has conflicting bare and {target!r} "
                    "test-machine settings; reconcile them before convergence"
                )
            verified = (
                max(
                    value
                    for value in (row["verified_at"], existing[1], "")
                    if value is not None
                )
                or None
            )
            created = min(str(row["created_at"]), str(existing[2]))
            conn.execute(
                "UPDATE project_capabilities SET verified_at="
                f"{marker},created_at={marker} "
                f"WHERE project_id={marker} AND type={marker}",
                (verified, created, project_id, target),
            )
            conn.execute(
                "DELETE FROM project_capabilities "
                f"WHERE project_id={marker} AND type={marker}",
                (project_id, BARE_TYPE),
            )
        renamed[project_id] = target
    return renamed


def _create_verification_table(conn: Any, table: str) -> None:
    conn.execute(
        f'CREATE TABLE "{table}" ('
        "project_id INTEGER NOT NULL, capability_type TEXT NOT NULL, "
        "status TEXT NOT NULL CHECK(status IN "
        "('configured_unverified','verified','error')), "
        "checked_at TEXT, receipt_json TEXT NOT NULL DEFAULT '{}', "
        "error_code TEXT, updated_at TEXT NOT NULL, "
        "PRIMARY KEY(project_id, capability_type), "
        "FOREIGN KEY(project_id, capability_type) REFERENCES "
        "project_capabilities(project_id, type) ON DELETE CASCADE)"
    )


def _verification_target(
    conn: Any,
    *,
    project_id: int,
    renamed: dict[int, str],
) -> str:
    marker = _p(conn)
    rows = conn.execute(
        "SELECT type FROM project_capabilities "
        f"WHERE project_id={marker} AND type LIKE {marker} ORDER BY type",
        (project_id, TYPE_PREFIX + "%"),
    ).fetchall()
    types = [str(row[0]) for row in rows]
    if len(types) == 1:
        return types[0]
    renamed_type = renamed.get(project_id)
    if renamed_type is not None and renamed_type in types:
        return renamed_type
    raise ValueError(
        f"project {project_id} has {len(types)} test-machine rows for one "
        "project-scoped verification receipt; reconcile the rows before convergence"
    )


def _rebuild_verifications(conn: Any, renamed: dict[int, str]) -> None:
    if not _table_exists(conn, VERIFICATION_TABLE):
        _create_verification_table(conn, VERIFICATION_TABLE)
        return
    if _column_exists(conn, VERIFICATION_TABLE, "capability_type"):
        return
    rows = conn.execute(
        f"SELECT project_id,status,checked_at,receipt_json,error_code,updated_at "
        f"FROM {VERIFICATION_TABLE} ORDER BY project_id"
    ).fetchall()
    conn.execute(f'DROP TABLE IF EXISTS "{REPLACEMENT_TABLE}"')
    _create_verification_table(conn, REPLACEMENT_TABLE)
    marker = _p(conn)
    for raw in rows:
        row = dict(raw)
        capability_type = _verification_target(
            conn,
            project_id=int(row["project_id"]),
            renamed=renamed,
        )
        conn.execute(
            f'INSERT INTO "{REPLACEMENT_TABLE}"('
            "project_id,capability_type,status,checked_at,receipt_json,"
            f"error_code,updated_at) VALUES({','.join([marker] * 7)})",
            (
                int(row["project_id"]),
                capability_type,
                row["status"],
                row["checked_at"],
                row["receipt_json"],
                row["error_code"],
                row["updated_at"],
            ),
        )
    conn.execute(f'DROP TABLE "{VERIFICATION_TABLE}"')
    conn.execute(f'ALTER TABLE "{REPLACEMENT_TABLE}" RENAME TO "{VERIFICATION_TABLE}"')


def apply(conn: Any) -> None:
    renamed = _rename_capabilities(conn)
    _rebuild_verifications(conn, renamed)


def invariants(conn: Any) -> None:
    if not _table_exists(conn, "project_capabilities"):
        return
    marker = _p(conn)
    bare = conn.execute(
        f"SELECT COUNT(*) FROM project_capabilities WHERE type={marker}",
        (BARE_TYPE,),
    ).fetchone()[0]
    assert int(bare) == 0, "bare test-machine capability rows must be gone"
    assert _column_exists(conn, VERIFICATION_TABLE, "capability_type"), (
        "test-machine verification rows must name their capability type"
    )
    orphaned = conn.execute(
        f"SELECT COUNT(*) FROM {VERIFICATION_TABLE} v "
        "LEFT JOIN project_capabilities c ON c.project_id=v.project_id "
        "AND c.type=v.capability_type WHERE c.project_id IS NULL"
    ).fetchone()[0]
    assert int(orphaned) == 0, "test-machine verification rows must own a capability"


__all__ = [
    "MINIMUM_SERVING_VERSION",
    "apply",
    "invariants",
]
