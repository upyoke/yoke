# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from unittest.mock import Mock

from yoke_core.domain import decision_request_requester_label as labels


def add_holdings_schema(conn):
    conn.executescript("""
        ALTER TABLE harness_sessions ADD COLUMN machine_id TEXT;
        ALTER TABLE work_claims ADD COLUMN claimed_at TEXT DEFAULT 'now';
        ALTER TABLE work_claims ADD COLUMN reason TEXT;
        CREATE TABLE session_relays (machine_id TEXT, hostname TEXT, last_seen_at TEXT);
        CREATE TABLE session_launches (launch_id TEXT, registered_session_id TEXT, native_session_id TEXT, item_id INTEGER, created_at TEXT);
        CREATE TABLE epic_tasks (epic_id INTEGER, task_num INTEGER, item_worktree_id INTEGER);
        CREATE TABLE item_worktrees (id INTEGER, item_id INTEGER, state TEXT, lane_role TEXT);
    """)
