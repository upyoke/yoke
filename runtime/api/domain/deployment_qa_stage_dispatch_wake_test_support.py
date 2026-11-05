# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_deployment_run

from typing import Any

from unittest import mock

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    _claim,
    _project,
    _recipients,
    seed_session,
)

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_core.domain.project_identity import render_item_ref

from yoke_core.domain import deployment_qa_dispatch_wait_notice as wait_notice_mod

from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)

from yoke_core.domain.deployment_qa_stage_wake import stage_wait_idempotency_key

from yoke_core.domain.work_claim_targets import make_item_target


def _run(conn: Any, run_id: str) -> None:
    insert_deployment_run(
        conn,
        id=run_id,
        project_id=1,
        flow="flow-x",
        status="executing",
        created_at="2026-09-14T00:00:00Z",
    )
    conn.commit()


def _member(conn: Any, run_id: str, item_id: int) -> None:
    insert_item(conn, id=item_id, project_sequence=item_id, workflow_id="issue")
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) VALUES (%s,%s,%s)",
        (run_id, item_id, "2026-09-14T00:00:00Z"),
    )
    conn.commit()


_WAITING = {
    "accepted": False,
    "reasons": ["awaiting agent verdict"],
    "request_id": None,
}
