# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from collections.abc import Iterator

from contextlib import contextmanager

from typing import Any

from unittest import mock

from runtime.api.domain.deployment_qa_stage_execution_test_support import (
    _plan,
    _seed_run,
    _stages,
)

from runtime.api.fixtures.dispatch_actor import register_session_actor

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain import (
    deployment_qa_takeover_identity,
    qa_deployment_function_subject,
)

from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups

from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
)

from yoke_core.domain.yoke_function_dispatch import dispatch

SESSION = "subject-once-session"

STAGE = "item-qa"


def _shared_execution(conn: Any, run_id: str, members: tuple[int, ...]) -> dict:
    slug = f"shared-{run_id}"
    plan_id = _plan(conn, slug)
    stages = _stages(plan_id)
    stages[1].pop("cases")
    _seed_run(conn, run_id=run_id, stages=stages, members=members)
    for member in members:
        conn.execute(
            "INSERT INTO qa_plan_item_attachments(item_id,plan_id,transition_id,"
            "qa_phase,attached_at) VALUES (%s,%s,'release','post_deploy',"
            "'2026-10-14T00:00:00Z')",
            (member, plan_id),
        )
    conn.commit()
    ensure_groups(conn, run_id, STAGE)
    conn.commit()
    actor_id = register_session_actor(conn, SESSION)
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=None,
        plan=slug,
        actor_id=str(actor_id),
        session_id=SESSION,
    )
    assert execution["deployment_member_item_id"] is None
    return execution
