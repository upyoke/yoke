# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import sqlite3

import pytest

from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)

from yoke_core.domain.session_control_health_facts import session_health_facts

from yoke_core.domain.session_stale_alive_probe import probe_key

from yoke_core.domain.work_claim_targets import make_item_target

from yoke_core.domain.workflow_definition_codec import (
    canonical_definition_json,
    definition_digest,
)

SESSION = "session-1"

DEPENDENT = 41

BLOCKER = 42

WORKFLOW_VERSION = 7

@pytest.fixture()
def conn() -> sqlite3.Connection:
    connection = sqlite3.connect(":memory:")
    connection.row_factory = sqlite3.Row
    connection.executescript(
        """
        CREATE TABLE projects (
            id INTEGER PRIMARY KEY, slug TEXT, public_item_prefix TEXT
        );
        CREATE TABLE items (
            id INTEGER PRIMARY KEY,
            project_id INTEGER,
            project_sequence INTEGER,
            status TEXT,
            merged_at TEXT,
            workflow_id TEXT,
            workflow_version_id INTEGER
        );
        CREATE TABLE item_dependencies (
            id INTEGER PRIMARY KEY,
            dependent_item_id INTEGER,
            blocking_item_id INTEGER,
            gate_point TEXT,
            satisfaction TEXT,
            created_at TEXT NOT NULL DEFAULT '2026-01-01T00:00:00Z'
        );
        CREATE TABLE workflow_versions (
            id INTEGER PRIMARY KEY,
            version INTEGER,
            definition_json TEXT,
            definition_digest TEXT
        );
        CREATE TABLE item_worktrees (
            id INTEGER PRIMARY KEY,
            item_id INTEGER,
            branch TEXT,
            state TEXT,
            lane_role TEXT
        );
        CREATE TABLE work_claims (
            id INTEGER PRIMARY KEY,
            session_id TEXT,
            target_kind TEXT,
            scope TEXT,
            claimed_at TEXT,
            released_at TEXT
        );
        CREATE TABLE session_messages (
            message_id TEXT PRIMARY KEY,
            idempotency_key TEXT,
            cancelled_at TEXT,
            expires_at TEXT
        );
        CREATE TABLE session_message_recipients (
            message_id TEXT,
            session_id TEXT,
            state TEXT,
            created_at TEXT,
            wake_attempt_count INTEGER
        );
        """
    )
    connection.execute("INSERT INTO projects VALUES (1,'yoke','YOK')")
    fixture = builtin_workflow_definition("dash")
    definition = fixture["definition"]
    connection.execute(
        "INSERT INTO workflow_versions VALUES (?,?,?,?)",
        (
            WORKFLOW_VERSION,
            int(fixture["canon_version"]),
            canonical_definition_json(definition),
            definition_digest(definition),
        ),
    )
    for item_id, status in ((DEPENDENT, "implementing"), (BLOCKER, "implementing")):
        connection.execute(
            "INSERT INTO items VALUES (?,?,?,?,?,?,?)",
            (item_id, 1, item_id, status, None, "dash", WORKFLOW_VERSION),
        )
    connection.execute(
        "INSERT INTO work_claims VALUES (?,?,?,?,?,?)",
        (
            1,
            SESSION,
            "item",
            make_item_target(DEPENDENT).scope_json(),
            "2026-08-22T11:00:00Z",
            None,
        ),
    )
    return connection
