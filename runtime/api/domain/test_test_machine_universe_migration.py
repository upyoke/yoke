"""Prove that machine identity and both receipt kinds survive the cutover."""

from pathlib import Path
import sqlite3

import pytest

from yoke_core.domain import migrations
from yoke_core.domain.migration_history import load_migration_module


NAMES = ("linux-lab", "mac-lab", "windows-lab", "windows-native-lab")
NOW = "2026-11-18T14:00:00Z"


def _migration():
    path = Path(migrations.__file__).parent / "0114_test_machines_universe_entity.py"
    return load_migration_module(path, path.stem)


@pytest.fixture
def legacy():
    with sqlite3.connect(":memory:") as conn:
        conn.executescript(
            """
            PRAGMA foreign_keys=ON;
            CREATE TABLE projects (id INTEGER PRIMARY KEY);
            INSERT INTO projects VALUES (1), (2);
            CREATE TABLE project_capabilities (
                project_id INTEGER, type TEXT, settings TEXT, verified_at TEXT,
                created_at TEXT, PRIMARY KEY(project_id, type)
            );
            CREATE TABLE capability_secrets (project_id INTEGER, type TEXT, key TEXT);
            CREATE TABLE test_machine_verifications (
                project_id INTEGER, capability_type TEXT, status TEXT, checked_at TEXT,
                receipt_json TEXT, error_code TEXT, updated_at TEXT,
                PRIMARY KEY(project_id, capability_type),
                FOREIGN KEY(project_id, capability_type)
                    REFERENCES project_capabilities(project_id, type) ON DELETE CASCADE
            );
            CREATE TABLE test_machine_operation_receipts (
                project_id INTEGER, capability_type TEXT, operation TEXT, status TEXT,
                performed_at TEXT, receipt_json TEXT, error_code TEXT, lease_id INTEGER,
                contract_digest TEXT, updated_at TEXT,
                PRIMARY KEY(project_id, capability_type, operation),
                FOREIGN KEY(project_id, capability_type)
                    REFERENCES project_capabilities(project_id, type) ON DELETE CASCADE
            );
            """
        )
        yield conn


def test_cutover_preserves_settings_owner_and_receipts_on_replay(legacy):
    rows = []
    for index, name in enumerate(NAMES):
        project = index % 2 + 1
        kind = f"test-machine:{name}"
        settings = f'{{ "resource_name": "{name}" }}'
        rows.append((name, settings, project, NOW, NOW, None))
        legacy.execute(
            "INSERT INTO project_capabilities VALUES (?, ?, ?, ?, ?)",
            (project, kind, settings, NOW, NOW),
        )
        legacy.execute(
            "INSERT INTO test_machine_verifications VALUES (?, ?, 'verified', ?, '{}', NULL, ?)",
            (project, kind, NOW, NOW),
        )
        legacy.execute(
            "INSERT INTO test_machine_operation_receipts VALUES "
            "(?, ?, 'reset', 'verified', ?, '{}', NULL, 42, 'digest', ?)",
            (project, kind, NOW, NOW),
        )
    legacy.execute("INSERT INTO project_capabilities VALUES (1, 'github', '{}', NULL, ?)", (NOW,))
    legacy.execute("INSERT INTO capability_secrets VALUES (1, ?, 'admin_password')", (f"test-machine:{NAMES[-1]}",))
    migration = _migration()
    assert migration.MINIMUM_SERVING_VERSION == "next-release"
    for _ in range(2):
        migration.apply(legacy)
        migration.invariants(legacy)
    assert legacy.execute(
        "SELECT name, settings, power_project_id, verified_at, created_at, yoke_started_at "
        "FROM test_machines ORDER BY name"
    ).fetchall() == rows
    assert legacy.execute("SELECT type FROM project_capabilities").fetchall() == [("github",)]
    assert legacy.execute("SELECT key FROM capability_secrets").fetchall() == []
    assert legacy.execute(
        "SELECT m.name, v.status FROM test_machine_verifications v "
        "JOIN test_machines m ON m.id=v.test_machine_id ORDER BY m.name"
    ).fetchall() == [(name, "verified") for name in NAMES]
    assert legacy.execute(
        "SELECT m.name, r.operation, r.lease_id, r.contract_digest "
        "FROM test_machine_operation_receipts r JOIN test_machines m "
        "ON m.id=r.test_machine_id ORDER BY m.name"
    ).fetchall() == [(name, "reset", 42, "digest") for name in NAMES]
    legacy.execute("DELETE FROM test_machines WHERE name=?", (NAMES[0],))
    for table in ("test_machine_verifications", "test_machine_operation_receipts"):
        assert legacy.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 3


def test_duplicate_universe_names_refuse_before_writes(legacy):
    legacy.executemany(
        "INSERT INTO project_capabilities VALUES (?, ?, '{}', NULL, ?)",
        [(project, "test-machine:shared", NOW) for project in (1, 2)],
    )
    with pytest.raises(ValueError, match="duplicate Test Machine names: shared"):
        _migration().apply(legacy)
    assert legacy.execute("SELECT COUNT(*) FROM project_capabilities").fetchone()[0] == 2
    assert legacy.execute(
        "SELECT name FROM sqlite_master WHERE name='test_machines'"
    ).fetchone() is None
