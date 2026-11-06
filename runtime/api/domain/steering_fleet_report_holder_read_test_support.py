# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.fixtures.backlog import insert_item

from runtime.api.fixtures.statement_counter import CountingConnection

from runtime.api.steering_fleet_test_helpers import (
    LONG_AGO,
    NOW,
    PROJECT_ID,
    seed_session,
    seed_steering_scope,
)

from yoke_core.domain.steering_fleet_report_holders import claim_holders

from yoke_core.domain.work_claim_targets import make_item_target


def _claim(conn, session_id: str, item_id: int, *, released_at: str | None = None):
    target = make_item_target(item_id)
    conn.execute(
        "INSERT INTO work_claims "
        "(session_id,target_kind,scope,claim_type,claimed_at,last_heartbeat,"
        "released_at) VALUES (%s,%s,%s,'exclusive',%s,%s,%s)",
        (
            session_id,
            target.kind,
            target.scope_json(),
            LONG_AGO,
            LONG_AGO,
            released_at,
        ),
    )
    conn.commit()
