# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.dash_posture_deployment_containment_test_support import dash_db_path as dash_db_path

import json

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import (
    insert_item,
    insert_qa_requirement,
    insert_qa_run,
)

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

from yoke_core.domain.dash_execution import record_dash_evidence

from yoke_core.domain.path_claims_register import register_for_item

from yoke_core.domain.dash_posture_gate import evaluate

from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.domain.qa_workflow_binding_validation import (
    ITEM_POSTURE_VERIFICATION_TRANSITION,
)

from yoke_core.domain.workflow_status_transition_preflight import (
    prepare_status_transition,
)


def _insert_dash(
    conn,
    *,
    item_id: int,
    posture: dict,
    status: str = "reviewing-implementation",
) -> None:
    insert_item(
        conn,
        id=item_id,
        workflow_id="dash",
        status=status,
        source="901",
        workflow_posture=json.dumps(posture),
    )


def _insert_session(conn, session_id: str) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id, executor, provider, model, workspace, project_id, "
        "offered_at, last_heartbeat, actor_id) "
        "VALUES (%s, 'codex', 'openai', 'gpt', '/tmp', 1, %s, %s, 901)",
        (session_id, now, now),
    )
    conn.commit()
