# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.fixtures.actor_roles import seed_project_role

from typing import Any

from runtime.api.domain.coordination_claim_test_support import (
    PROJECT_YOKE,
    seed_project,
)

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    HOLDER_B,
    _bodies,
    _claim,
    _recipients,
    seed_session,
)

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_core.domain import deployment_delivery_close_out_notice as notice

from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    seed_roles_and_permissions,
)

from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.domain.deployment_delivery_close_out_notice import (
    delivery_cleared_idempotency_key,
    notify_delivery_cleared,
)

from yoke_core.domain.session_mode import SESSION_MODE_PARKED, set_session_mode

from yoke_core.domain.work_claim_targets import make_item_target, make_steering_target

from yoke_core.domain.workflow_behavior import delivery_redirect_stage

from yoke_core.domain.workflow_runtime import load_item_workflow_runtime

COMPLETION_FLOW = "prod-flow"


def _project(conn: Any) -> None:
    seed_project(conn, PROJECT_YOKE, "yoke")
    seed_roles_and_permissions(conn)
    seed_project_role(conn, actor_id=1, project_id=PROJECT_YOKE, role_name=ROLE_OWNER)


def _run(conn: Any, run_id: str, *, flow: str, members: tuple[int, ...]) -> None:
    now = iso8601_now()
    from runtime.api.fixtures.backlog_inserts import insert_deployment_run

    if (
        conn.execute("SELECT 1 FROM deployment_runs WHERE id=%s", (run_id,)).fetchone()
        is None
    ):
        insert_deployment_run(
            conn,
            id=run_id,
            project_id=PROJECT_YOKE,
            flow=flow,
            status="succeeded",
            created_at=now,
        )
    from runtime.api.fixtures.completed_delivery import pin_run_delivery

    pin_run_delivery(conn, run_id)
    for item_id in members:
        conn.execute(
            "INSERT INTO deployment_run_items (run_id,item_id,added_at) "
            "VALUES (%s,%s,%s)",
            (run_id, item_id, now),
        )
    conn.commit()


def _member_at_release_wait(conn: Any, item_id: int, *, status: str = "") -> None:
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id="dash",
        status="idea",
        deployment_flow=COMPLETION_FLOW,
    )
    stage = delivery_redirect_stage(load_item_workflow_runtime(conn, item_id))
    assert stage, "the dash pin must declare a release wait"
    conn.execute("UPDATE items SET status=%s WHERE id=%s", (status or stage, item_id))
    conn.commit()


def _parked_owner(conn: Any, session_id: str, item_id: int) -> None:
    seed_session(conn, session_id)
    _claim(
        conn,
        session_id=session_id,
        target_kind="item",
        scope_json=make_item_target(item_id).scope_json(),
    )
    set_session_mode(conn, session_id, SESSION_MODE_PARKED, "awaiting delivery")
