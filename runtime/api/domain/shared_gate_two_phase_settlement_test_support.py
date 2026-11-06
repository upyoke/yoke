# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.fixtures.backlog_inserts import insert_deployment_run

from typing import Any

from runtime.api.domain.deployment_delivery_close_out_notice_test_support import (
    COMPLETION_FLOW,
    _member_at_release_wait,
    _parked_owner,
    _project,
)

from runtime.api.domain.no_obligation_member_close_out_test_support import (
    _no_obligation,
    _ready_member,
)

from runtime.api.domain.run_success_member_settlement_test_support import (
    _claim_held,
    _run,
    _status,
)

from runtime.api.domain.status_transition_preflight_test_support import (
    _isolate_status_effects,
)

from runtime.api.fixtures.dispatch_actor import register_session_actor

from runtime.api.fixtures.runtime import DEFAULT_TEST_SESSION_ID

from yoke_core.domain import delivery_member_close_effects as close_effects

from yoke_core.domain import delivery_member_close_steps as close_out

from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.domain.deployment_run_collective_finalization import mark_settling

from yoke_core.domain.deployment_run_settlement_refusal import HELD_WITH_RUN

from yoke_core.domain.deployment_runs_crud_mutate import cmd_update

from yoke_core.domain.project_identity import render_item_ref

MEMBERS = (9861, 9862, 9863, 9864, 9865)

REASON = "nothing observable once deployed"


def _holder(item_id: int) -> str:
    return f"sess-settle-holder-{item_id}"


def _executing_run(conn: Any, run_id: str) -> None:
    now = iso8601_now()
    insert_deployment_run(
        conn,
        id=run_id,
        project_id=1,
        flow=COMPLETION_FLOW,
        status="executing",
        created_at=now,
    )
    from runtime.api.fixtures.completed_delivery import pin_run_delivery

    pin_run_delivery(conn, run_id)
    for item_id in MEMBERS:
        conn.execute(
            "INSERT INTO deployment_run_items (run_id,item_id,added_at) "
            "VALUES (%s,%s,%s)",
            (run_id, item_id, now),
        )
    conn.commit()


def _five_ready_members(conn: Any, *, without_evidence: int = 0) -> str:
    _project(conn)
    for item_id in MEMBERS:
        if item_id == without_evidence:
            _member_at_release_wait(conn, item_id)
            _parked_owner(conn, _holder(item_id), item_id)
        else:
            _ready_member(conn, item_id, _holder(item_id))
        _no_obligation(conn, item_id, reason=REASON)
    return _status(conn, MEMBERS[0])
