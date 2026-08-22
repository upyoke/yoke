"""Cutover coverage for session surface and organization identity columns."""

from __future__ import annotations

import json
import sqlite3

import pytest

from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import (
    declared_minimum,
    removes_a_surface,
)
from yoke_core.domain.schema_common import _column_exists


ENTRY_NAME = "0015_session_surface_and_organization_domain"


def _entry():
    directory = history_dir(migration_history_package)
    record = next(
        candidate
        for candidate in ordered_entries(directory)
        if candidate.name == ENTRY_NAME
    )
    return load_migration_module(directory / f"{record.name}.py", record.name)


entry = _entry()


def _retired_shape() -> sqlite3.Connection:
    conn = sqlite3.connect(":memory:")
    conn.executescript(
        """
        CREATE TABLE harness_sessions (
            session_id TEXT PRIMARY KEY,
            executor TEXT NOT NULL,
            executor_display_name TEXT,
            capabilities TEXT NOT NULL DEFAULT '[]'
        );
        CREATE TABLE organizations (
            id INTEGER PRIMARY KEY,
            slug TEXT NOT NULL,
            auto_join_domain TEXT
        );
        CREATE TABLE events (
            event_id TEXT PRIMARY KEY,
            source_type TEXT NOT NULL,
            session_id TEXT,
            severity TEXT NOT NULL,
            event_kind TEXT NOT NULL,
            event_type TEXT NOT NULL,
            event_name TEXT NOT NULL,
            service TEXT NOT NULL,
            envelope TEXT NOT NULL,
            created_at TEXT NOT NULL
        );
        """
    )
    conn.executemany(
        "INSERT INTO harness_sessions "
        "(session_id, executor, executor_display_name) VALUES (?, ?, ?)",
        (
            ("s-claude", "claude", "claude-cli"),
            ("s-codex", "codex", "codex-goal"),
            ("s-cursor", "cursor", None),
        ),
    )
    conn.execute(
        "INSERT INTO organizations (id, slug, auto_join_domain) "
        "VALUES (1, 'default', '@Example.com')"
    )
    conn.commit()
    return conn


def _boot_converged_shape() -> sqlite3.Connection:
    conn = _retired_shape()
    conn.execute("ALTER TABLE harness_sessions ADD COLUMN executor_surface TEXT")
    conn.execute("ALTER TABLE organizations ADD COLUMN domain TEXT")
    conn.execute(
        "ALTER TABLE organizations ADD COLUMN settings TEXT NOT NULL DEFAULT '{}'"
    )
    conn.commit()
    return conn


def test_cutover_preserves_valid_values_and_normalizes_legacy_rows():
    conn = _retired_shape()

    entry.apply(conn)
    entry.invariants(conn)

    claude = conn.execute(
        "SELECT executor, executor_surface FROM harness_sessions "
        "WHERE session_id='s-claude'"
    ).fetchone()
    codex = conn.execute(
        "SELECT executor, executor_surface FROM harness_sessions "
        "WHERE session_id='s-codex'"
    ).fetchone()
    assert claude == ("claude-code", "claude-cli")
    assert codex == ("codex", None)
    assert not _column_exists(conn, "harness_sessions", "capabilities")
    assert _column_exists(conn, "harness_sessions", "executor_version")
    assert _column_exists(conn, "harness_sessions", "machine_id")


def test_invalid_surface_emits_one_deterministic_audit_record():
    conn = _retired_shape()

    entry.apply(conn)
    entry.apply(conn)

    rows = conn.execute(
        "SELECT event_name, envelope FROM events ORDER BY event_id"
    ).fetchall()
    assert len(rows) == 1
    assert rows[0][0] == entry.SURFACE_AUDIT_EVENT
    assert json.loads(rows[0][1]) == {
        "discarded_surface": "codex-goal",
        "row_count": 1,
    }


def test_existing_domain_enables_verified_membership_during_rename():
    conn = _retired_shape()

    entry.apply(conn)

    row = conn.execute(
        "SELECT domain, settings FROM organizations WHERE id=1"
    ).fetchone()
    assert row[0] == "@Example.com"
    assert json.loads(row[1]) == {
        "membership": {"auto_join_domain_verified": True},
    }


def test_boot_added_current_columns_fold_without_collision():
    conn = _boot_converged_shape()

    entry.apply(conn)
    entry.invariants(conn)

    assert (
        conn.execute(
            "SELECT executor_surface FROM harness_sessions WHERE session_id='s-claude'"
        ).fetchone()[0]
        == "claude-cli"
    )
    assert (
        conn.execute("SELECT domain FROM organizations WHERE id=1").fetchone()[0]
        == "@Example.com"
    )


def test_unknown_executor_family_fails_loudly_with_counts():
    conn = _retired_shape()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, executor_display_name) "
        "VALUES ('s-unknown', 'invented', 'codex-cli')"
    )

    with pytest.raises(
        AssertionError,
        match=r"unknown harness session executor families.*invented.*\(1\)",
    ):
        entry.apply(conn)


def test_invariants_reject_retired_or_missing_columns():
    conn = _retired_shape()
    with pytest.raises(AssertionError, match="retired"):
        entry.invariants(conn)

    entry.apply(conn)
    conn.execute("ALTER TABLE harness_sessions DROP COLUMN machine_id")
    with pytest.raises(AssertionError, match="machine_id"):
        entry.invariants(conn)


def test_entry_is_idempotent_and_declares_a_serving_floor():
    conn = _retired_shape()
    entry.apply(conn)
    entry.apply(conn)
    entry.invariants(conn)

    source = (history_dir(migration_history_package) / f"{ENTRY_NAME}.py").read_text(
        encoding="utf-8"
    )
    assert removes_a_surface(source)
    assert declared_minimum(entry) == entry.MINIMUM_SERVING_VERSION
