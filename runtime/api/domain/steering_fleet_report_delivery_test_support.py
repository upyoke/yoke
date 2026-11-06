# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.fixtures.backlog import insert_item

from yoke_core.domain.steering_claims import acquire as acquire_steering

from yoke_core.domain.strategy_docs_defaults import seed_default_docs

from yoke_core.domain.steering_fleet_report_delivery import (
    claim_report_composition,
    confirm_steering_report_delivery,
    record_report_delivery,
    steered_project_id,
    steering_report_candidate,
    steering_report_for_delivery,
)

NOW = datetime(2026, 8, 26, 12, 0, 0, tzinfo=timezone.utc)

LONG_AGO = "2026-08-26T09:00:00.000000Z"

STEERING_SESSION = "steering-holder"

PLAIN_SESSION = "ordinary-worker"

PROJECT_ID = 1

ACTOR_ID = 2


def _seed_session(conn, session_id: str) -> None:
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, execution_level, workspace, "
        "project_id, mode, offered_at, last_heartbeat, actor_id, "
        "executor_surface) "
        "VALUES (%s, 'codex', 'openai', 'test-model', 'primary', %s, %s, "
        "'wait', %s, %s, %s, 'codex-cli')",
        (
            session_id,
            f"/tmp/{session_id}",
            PROJECT_ID,
            LONG_AGO,
            LONG_AGO,
            ACTOR_ID,
        ),
    )


@pytest.fixture
def steering_scope(test_db):
    """A steering holder, an ordinary session, and one long-unpicked item."""
    _seed_session(test_db, STEERING_SESSION)
    _seed_session(test_db, PLAIN_SESSION)
    insert_item(
        test_db,
        id=1,
        title="Unpicked work",
        status="idea",
        created_at=LONG_AGO,
        updated_at=LONG_AGO,
        spec="# Unpicked work\n\nA real spec body.",
    )
    test_db.commit()
    seed_default_docs(test_db, PROJECT_ID, "Yoke")
    acquire_steering(
        test_db,
        session_id=STEERING_SESSION,
        project_id=PROJECT_ID,
        reason="steering",
    )
    return test_db
