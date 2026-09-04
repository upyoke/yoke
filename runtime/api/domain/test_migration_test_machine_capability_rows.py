"""Hard-cutover migration coverage for independently keyed Test Macs."""

from __future__ import annotations

import importlib
import json
import sqlite3

import pytest

from yoke_core.domain.migration_serving_version import NEXT_RELEASE


MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0023_test_machine_capability_rows"
)
MACHINE = "mac-mini-lab"
MACHINE_TYPE = f"test-machine:{MACHINE}"


def _settings(*, host: str = "test-mac.local") -> str:
    return json.dumps(
        {
            "resource_name": MACHINE,
            "host": host,
            "user": "yoke-test",
            "host_kind": "mac-ssh",
            "operating_notes": "",
        },
        separators=(",", ":"),
        sort_keys=True,
    )


def _legacy_database() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.executescript(
        """
        CREATE TABLE project_capabilities (
            id INTEGER PRIMARY KEY,
            project_id INTEGER NOT NULL,
            type TEXT NOT NULL,
            settings TEXT NOT NULL DEFAULT '{}',
            verified_at TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(project_id, type)
        );
        CREATE TABLE test_machine_verifications (
            project_id INTEGER PRIMARY KEY,
            status TEXT NOT NULL,
            checked_at TEXT,
            receipt_json TEXT NOT NULL DEFAULT '{}',
            error_code TEXT,
            updated_at TEXT NOT NULL
        );
        """
    )
    conn.execute(
        "INSERT INTO project_capabilities("
        "project_id,type,settings,verified_at,created_at"
        ") VALUES(1,'test-machine',?,?,?)",
        (_settings(), "2026-08-01T12:00:00Z", "2026-08-01T11:00:00Z"),
    )
    conn.execute(
        "INSERT INTO test_machine_verifications("
        "project_id,status,checked_at,receipt_json,error_code,updated_at"
        ") VALUES(1,'verified',?,'{\"checks\":[]}',NULL,?)",
        ("2026-08-01T12:00:00Z", "2026-08-01T12:00:00Z"),
    )
    conn.commit()
    return conn


def _snapshot(conn: sqlite3.Connection) -> tuple[list[tuple], list[tuple]]:
    capabilities = [
        tuple(row)
        for row in conn.execute(
            "SELECT project_id,type,settings,verified_at,created_at "
            "FROM project_capabilities ORDER BY project_id,type"
        )
    ]
    verifications = [
        tuple(row)
        for row in conn.execute(
            "SELECT project_id,capability_type,status,checked_at,receipt_json,"
            "error_code,updated_at FROM test_machine_verifications "
            "ORDER BY project_id,capability_type"
        )
    ]
    return capabilities, verifications


def test_migration_moves_capability_and_receipt_to_the_machine_key() -> None:
    conn = _legacy_database()

    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)

    capability = conn.execute(
        "SELECT type,verified_at FROM project_capabilities WHERE project_id=1"
    ).fetchone()
    assert tuple(capability) == (MACHINE_TYPE, "2026-08-01T12:00:00Z")
    receipt = conn.execute(
        "SELECT capability_type,status,receipt_json "
        "FROM test_machine_verifications WHERE project_id=1"
    ).fetchone()
    assert tuple(receipt) == (MACHINE_TYPE, "verified", '{"checks":[]}')
    columns = {
        str(row["name"]): int(row["pk"])
        for row in conn.execute("PRAGMA table_info(test_machine_verifications)")
    }
    assert columns["project_id"] == 1
    assert columns["capability_type"] == 2


def test_migration_replay_is_a_no_op() -> None:
    conn = _legacy_database()
    MIGRATION.apply(conn)
    before = _snapshot(conn)

    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)

    assert _snapshot(conn) == before


def test_identical_preexisting_machine_row_is_folded() -> None:
    conn = _legacy_database()
    conn.execute(
        "INSERT INTO project_capabilities("
        "project_id,type,settings,verified_at,created_at"
        ") VALUES(1,?,?,NULL,?)",
        (MACHINE_TYPE, _settings(), "2026-08-01T10:00:00Z"),
    )

    MIGRATION.apply(conn)
    MIGRATION.invariants(conn)

    rows = conn.execute(
        "SELECT type,verified_at,created_at FROM project_capabilities"
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (MACHINE_TYPE, "2026-08-01T12:00:00Z", "2026-08-01T10:00:00Z")
    ]


def test_conflicting_preexisting_machine_row_refuses_convergence() -> None:
    conn = _legacy_database()
    conn.execute(
        "INSERT INTO project_capabilities("
        "project_id,type,settings,verified_at,created_at"
        ") VALUES(1,?,?,NULL,?)",
        (MACHINE_TYPE, _settings(host="other-mac.local"), "2026-08-01T10:00:00Z"),
    )

    with pytest.raises(ValueError, match="conflicting bare"):
        MIGRATION.apply(conn)


def test_migration_declares_the_next_serving_floor() -> None:
    assert MIGRATION.MINIMUM_SERVING_VERSION == NEXT_RELEASE
