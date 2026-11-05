# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import sqlite3

from datetime import datetime, timezone

from typing import Any

from runtime.api.domain.coordination_claim_test_support import PROJECT_YOKE

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    HOLDER_B,
    _claim,
    _project,
    seed_session,
)

from runtime.api.fixtures.backlog_inserts import insert_deployment_run, insert_item

from yoke_core.domain.deployment_qa_stage_wake import (
    notify_item_scoped_qa_wait,
    notify_run_scoped_qa_wait,
    run_stage_wait_idempotency_key,
    stage_wait_idempotency_key,
)

from yoke_core.domain.deployment_run_driver_attachment import (
    PHASE_EXECUTING,
    attach_driver,
)

from yoke_core.domain.deployment_qa_stage_wake_withdraw import (
    withdraw_deployment_qa_wait_wakes,
)

from yoke_core.domain.item_terminal_resources import release_for_terminal_transition

from yoke_core.domain.session_message_delivery import expire_due_recipients

from yoke_core.domain.work_claim_targets import make_item_target

from yoke_contracts.timestamps import parse_instant

RUN_ID = "run-20260920-011"

STAGE = "item-qa"

NOW = datetime(2026, 9, 21, 3, 12, tzinfo=timezone.utc)


def _message(conn: Any, key: str) -> tuple[str, datetime | None, str]:
    row = conn.execute(
        "SELECT message_id, cancelled_at, "
        "COALESCE(cancellation_reason,'') FROM session_messages "
        "WHERE idempotency_key=%s",
        (key,),
    ).fetchone()
    assert row is not None
    return str(row[0]), row[1], str(row[2])


def _seed_member(
    conn: Any, item_id: int, session_id: str, *, status: str = "idea"
) -> None:
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id="issue",
        status=status,
    )
    seed_session(conn, session_id)
    _claim(
        conn,
        session_id=session_id,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )


def _wait(conn: Any, item_id: int) -> str:
    result = notify_item_scoped_qa_wait(
        conn,
        run_id=RUN_ID,
        stage_name=STAGE,
        item_id=item_id,
        project_id=PROJECT_YOKE,
        reasons="awaiting agent verdict",
        names_cases=True,
    )
    assert result in ("delivered", "undelivered")
    return stage_wait_idempotency_key(RUN_ID, STAGE, item_id)


def _executing_run(conn: Any) -> None:
    insert_deployment_run(
        conn,
        id=RUN_ID,
        project_id=PROJECT_YOKE,
        status="executing",
        current_stage=STAGE,
    )
