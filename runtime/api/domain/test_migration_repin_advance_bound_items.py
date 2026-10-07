"""Open items on published advance-bound definitions are re-pinned before 0053."""

from __future__ import annotations

import copy
import importlib
import shutil
import sqlite3
from pathlib import Path

import pytest

from runtime.api.domain.migration_boot_test_helpers import (
    RESTORE_POINT,
    applied_names,
    apply_pending,
    connection as ledger_connection,
)
from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.builtin_workflow_canon import canon_generations
from yoke_core.domain.migration_history import history_dir, ordered_entries
from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)
from yoke_core.domain.workflow_schema import ensure_workflow_schema

REPIN = importlib.import_module(
    "yoke_core.domain.migrations.0060_repin_advance_bound_items"
)
RETIRE = importlib.import_module(
    "yoke_core.domain.migrations.0053_retire_advance_skill"
)


def _generation(workflow_id: str, canon_version: int) -> dict:
    for generation in canon_generations(workflow_id):
        if generation.canon_version == canon_version:
            return copy.deepcopy(generation.definition)
    raise AssertionError(f"no canon {workflow_id}.{canon_version}")


def _customized_issue() -> dict:
    definition = _generation("issue", 7)
    definition["stages"][0]["label"] = "local idea"
    return definition


def _schema(conn: sqlite3.Connection) -> sqlite3.Connection:
    conn.executescript(
        """
        CREATE TABLE projects (id INTEGER PRIMARY KEY, public_item_prefix TEXT);
        CREATE TABLE items (
            id INTEGER PRIMARY KEY, project_id INTEGER,
            project_sequence INTEGER, status TEXT
        );
        INSERT INTO projects VALUES (1, 'ACME');
        """
    )
    ensure_workflow_schema(conn)
    for workflow_id in ("issue", "task"):
        conn.execute(
            "INSERT INTO workflows (id, name, description, source, status, "
            "created_at, updated_at) "
            "VALUES (?, ?, '', 'built_in', 'active', 'now', 'now')",
            (workflow_id, workflow_id),
        )
    return conn


def _publish(conn, workflow_id: str, version: int, definition: dict) -> int:
    """Seed a stored row as an older build wrote it, without current validation.

    Current validation refuses `advance`, which is exactly the state an older
    universe still holds.
    """
    cursor = conn.execute(
        "INSERT INTO workflow_versions (workflow_id, version, "
        "definition_schema_version, definition_json, definition_digest, "
        "published_at, immutable_at) VALUES (?, ?, ?, ?, ?, 'then', 'then')",
        (
            workflow_id,
            version,
            int(definition["schema_version"]),
            canonical_definition_json(definition),
            definition_digest(definition),
        ),
    )
    return int(cursor.lastrowid)


def _item(conn, sequence: int, status: str, version_id: int) -> None:
    conn.execute(
        "INSERT INTO items (id, project_id, project_sequence, status, "
        "workflow_version_id) VALUES (?, 1, ?, ?, ?)",
        (sequence, sequence, status, version_id),
    )


def _pin(conn, item_id: int) -> tuple[str, int]:
    return conn.execute(
        "SELECT wv.workflow_id, wv.definition_digest FROM items i "
        "JOIN workflow_versions wv ON wv.id = i.workflow_version_id WHERE i.id = ?",
        (item_id,),
    ).fetchone()


def _digest(workflow_id: str, canon_version: int) -> str:
    return next(
        g.digest
        for g in canon_generations(workflow_id)
        if g.canon_version == canon_version
    )


def _published_universe(conn: sqlite3.Connection) -> dict[str, int]:
    """Older published pins, numbered as this universe numbered them."""
    pins = {
        "issue@1": _publish(conn, "issue", 1, _generation("issue", 1)),
        "issue@7": _publish(conn, "issue", 4, _generation("issue", 7)),
        "task@1": _publish(conn, "task", 1, _generation("task", 1)),
    }
    _item(conn, 1, "idea", pins["issue@1"])
    _item(conn, 2, "implementing", pins["issue@7"])
    _item(conn, 3, "idea", pins["task@1"])
    _item(conn, 4, "done", pins["issue@1"])
    _item(conn, 5, "cancelled", pins["task@1"])
    return pins


def test_published_pins_move_to_replacements_and_0053_then_passes():
    conn = _schema(sqlite3.connect(":memory:"))
    pins = _published_universe(conn)

    REPIN.apply(conn)

    issue_8, task_2 = _digest("issue", 8), _digest("task", 2)
    assert _pin(conn, 1) == ("issue", issue_8)
    assert _pin(conn, 2) == ("issue", issue_8)
    assert _pin(conn, 3) == ("task", task_2)
    # Terminal items keep their historical pins.
    assert conn.execute(
        "SELECT workflow_version_id FROM items WHERE id IN (4, 5) ORDER BY id"
    ).fetchall() == [(pins["issue@1"],), (pins["task@1"],)]
    # The replacement is appended at this universe's own next number.
    assert conn.execute(
        "SELECT version FROM workflow_versions WHERE definition_digest = ?",
        (issue_8,),
    ).fetchone() == (5,)
    REPIN.invariants(conn)
    RETIRE.apply(conn)
    RETIRE.invariants(conn)


def test_existing_replacement_version_is_reused_and_reapply_is_a_no_op():
    conn = _schema(sqlite3.connect(":memory:"))
    _published_universe(conn)
    held = _publish(conn, "issue", 9, _generation("issue", 8))

    REPIN.apply(conn)
    pins = conn.execute("SELECT id, workflow_version_id FROM items").fetchall()
    versions = conn.execute("SELECT COUNT(*) FROM workflow_versions").fetchone()
    REPIN.apply(conn)

    assert conn.execute(
        "SELECT workflow_version_id FROM items WHERE id = 1"
    ).fetchone() == (held,)
    assert conn.execute("SELECT id, workflow_version_id FROM items").fetchall() == pins
    assert conn.execute("SELECT COUNT(*) FROM workflow_versions").fetchone() == versions


def test_customized_advance_definition_refuses_and_changes_nothing():
    conn = _schema(sqlite3.connect(":memory:"))
    published = _publish(conn, "issue", 1, _generation("issue", 1))
    custom = _publish(conn, "issue", 2, _customized_issue())
    _item(conn, 1, "idea", published)
    _item(conn, 2, "refined-idea", custom)
    conn.commit()

    with pytest.raises(RuntimeError) as refusal:
        REPIN.apply(conn)
    conn.rollback()

    message = str(refusal.value)
    assert "repin_advance_customized_definition" in message
    assert "ACME-2 (issue@2, refined-idea)" in message
    assert "ACME-1" not in message
    assert "yoke workflows item migrate" in message
    assert "yoke items cancel" in message
    assert conn.execute(
        "SELECT workflow_version_id FROM items ORDER BY id"
    ).fetchall() == [(published,), (custom,)]


def test_universe_without_advance_pins_is_untouched():
    conn = _schema(sqlite3.connect(":memory:"))
    current = _publish(conn, "issue", 1, _generation("issue", 8))
    _item(conn, 1, "idea", current)

    REPIN.apply(conn)
    REPIN.invariants(conn)

    assert conn.execute("SELECT COUNT(*) FROM workflow_versions").fetchone() == (1,)


def test_declares_order_and_serving_floor():
    assert REPIN.PRECEDES == ("0053_retire_advance_skill",)
    assert REPIN.MINIMUM_SERVING_VERSION == "next-release"


def test_boot_applies_repin_before_retire_on_a_pre_0053_universe(tmp_path: Path):
    source = history_dir(migration_history_package)
    for name in ("0053_retire_advance_skill", "0060_repin_advance_bound_items"):
        shutil.copy(source / f"{name}.py", tmp_path / f"{name}.py")
    history = ordered_entries(tmp_path)
    conn = _schema(ledger_connection())
    conn.execute(
        "CREATE TABLE project_capabilities (id INTEGER PRIMARY KEY, "
        "type TEXT, settings TEXT)"
    )
    _published_universe(conn)
    conn.commit()

    outcome = apply_pending(
        conn,
        history=history,
        applied_by="test",
        running_version="",
        external_restore_point=RESTORE_POINT,
    )

    assert outcome.applied == (
        "0060_repin_advance_bound_items",
        "0053_retire_advance_skill",
    )
    assert applied_names(conn) == set(outcome.applied)
    assert _pin(conn, 1) == ("issue", _digest("issue", 8))
    assert _pin(conn, 3) == ("task", _digest("task", 2))
