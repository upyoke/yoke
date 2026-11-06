"""Release retirement refuses live gate references without rewriting history."""

from __future__ import annotations

import importlib
import json
import sqlite3

import pytest

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0099_retire_db_claim_" + "prose_gate"
)


def _database(*, current=2, items=()):
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE projects (id INTEGER PRIMARY KEY, public_item_prefix TEXT);
        CREATE TABLE workflow_versions (
            id INTEGER PRIMARY KEY, workflow_id TEXT, version INTEGER,
            definition_json TEXT
        );
        CREATE TABLE workflows (id TEXT PRIMARY KEY, current_version_id INTEGER);
        CREATE TABLE items (
            id INTEGER PRIMARY KEY, project_id INTEGER, project_sequence INTEGER,
            status TEXT, workflow_version_id INTEGER
        );
        INSERT INTO projects VALUES (1, 'ACME');
        """
    )
    for version, gates in ((1, [{"id": MIGRATION.RETIRED_GATE_ID}]), (2, [])):
        conn.execute(
            "INSERT INTO workflow_versions VALUES (?, 'custom', ?, ?)",
            (version, version, json.dumps({
                "stages": [{"id": "review", "gates": gates}],
                "terminal_stage_ids": ["done", "archived"],
            })),
        )
    conn.execute("INSERT INTO workflows VALUES ('custom', ?)", (current,))
    for item_id, (stage, version) in enumerate(items, start=1):
        conn.execute(
            "INSERT INTO items VALUES (?, 1, ?, ?, ?)",
            (item_id, item_id, stage, version),
        )
    return conn


def _snapshot(conn):
    return tuple(
        (table, tuple(conn.execute(f"SELECT * FROM {table} ORDER BY 1")))
        for table in ("items", "workflow_versions", "workflows", "projects")
    )


@pytest.mark.parametrize("operation", [MIGRATION.apply, MIGRATION.invariants])
@pytest.mark.parametrize("current", [1, 2])
def test_open_pins_refuse_with_each_item_version_and_recovery(operation, current):
    conn = _database(current=current, items=[("review", 1), ("idea", 1), ("done", 1)])
    before = _snapshot(conn)
    changes = conn.total_changes
    with pytest.raises(RuntimeError) as refusal:
        operation(conn)
    message = str(refusal.value)
    assert f"retired_{MIGRATION.RETIRED_GATE_ID}_gate_pinned:" in message
    for ref, stage in (("ACME-1", "review"), ("ACME-2", "idea")):
        assert f"{ref} (custom@1, {stage})" in message
        assert f"yoke workflows item migrate {ref}" in message
    assert "ACME-3" not in message
    assert "On the build this universe is running now" in message
    if current == 1:
        assert "Current workflow versions: custom@1" in message
        assert "yoke workflows current set" in message
    assert _snapshot(conn) == before
    assert conn.total_changes == changes


@pytest.mark.parametrize("operation", [MIGRATION.apply, MIGRATION.invariants])
def test_current_version_alone_refuses_without_mutating_rows(operation):
    conn = _database(current=1, items=[("done", 1)])
    before = _snapshot(conn)
    changes = conn.total_changes
    with pytest.raises(RuntimeError) as refusal:
        operation(conn)
    message = str(refusal.value)
    assert "Current workflow versions: custom@1" in message
    assert "yoke workflows current set" in message
    assert "Non-terminal item pins" not in message
    assert _snapshot(conn) == before
    assert conn.total_changes == changes


def test_terminal_history_and_clean_open_pins_pass_repeatedly_unchanged():
    conn = _database(items=[
        ("done", 1), ("cancelled", 1), ("stopped", 1), ("archived", 1), ("review", 2),
    ])
    before = _snapshot(conn)
    for _ in range(2):
        MIGRATION.apply(conn)
        MIGRATION.invariants(conn)
    assert _snapshot(conn) == before

