# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

from datetime import datetime, timezone

import pytest

from runtime.api.api_items_test_helpers import (
    _client_for_db,
    make_test_db_fixture,
)

from runtime.api.fixtures.backlog import insert_item

from runtime.api.api_hooks_evaluate_route_test_support import _request_body

from yoke_core.domain.work_claim_targets import make_item_target


def _seed_recent_claim_denial_state(
    *,
    session_id: str,
    holder_session_id: str,
    item_id: int,
) -> None:
    from yoke_core.domain import db_helpers

    now = datetime.now(timezone.utc)
    conn = db_helpers.connect()
    try:
        # The guard resolves the command's public ref, so the item exists
        # (its project sequence equals its id in this fixture project).
        insert_item(conn, id=item_id, title="claim-guard item")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS session_tool_calls (
                id INTEGER PRIMARY KEY,
                session_id TEXT NOT NULL,
                tool_use_id TEXT NOT NULL,
                tool_name TEXT,
                started_at TIMESTAMPTZ NOT NULL,
                completed_at TIMESTAMPTZ,
                outcome TEXT,
                command_summary TEXT
            )
            """
        )
        conn.execute(
            """INSERT INTO session_tool_calls
               (id, session_id, tool_use_id, tool_name, started_at,
                completed_at, outcome, command_summary)
               VALUES (%s, %s, %s, 'Bash', %s, %s, 'denied', %s)""",
            (
                901,
                session_id,
                "claim-denied",
                now,
                now,
                (
                    "python3 -m yoke_core.api.service_client "
                    f"claim-work --item YOK-{item_id}"
                ),
            ),
        )
        conn.execute(
            """INSERT INTO work_claims
               (id, session_id, target_kind, scope, claim_type,
                claimed_at, last_heartbeat, released_at, release_reason)
               VALUES (%s, %s, 'item', %s, 'exclusive',
                       '2026-06-16T17:59:00Z', '2026-06-16T18:00:00Z',
                       NULL, NULL)""",
            (902, holder_session_id, make_item_target(item_id).scope_json()),
        )
        conn.commit()
    finally:
        conn.close()
