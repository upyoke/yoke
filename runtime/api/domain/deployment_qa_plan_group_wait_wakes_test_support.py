# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import pytest

from runtime.api.domain.deployment_qa_plan_groups_test_support import (
    MEMBERS,
    RUN,
    SLUG,
    _begin,
    _pass_group,
    _seed,
)

from runtime.api.domain.deployment_qa_plan_group_scenarios_test_support import (
    _dispatch,
    _form,
    _manual_plan,
)

from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
    HOLDER_A,
    HOLDER_B,
    _bodies,
    _claim,
    _project,
    _recipients,
    seed_session,
)

from runtime.api.fixtures.deployment_run_driver_fixture import DRIVER_SESSION

from yoke_core.domain.deployment_qa_plan_group_dispatch import plan_groups_wait_key

from yoke_core.domain.deployment_qa_plan_groups import run_groups

from yoke_core.domain.deployment_qa_stage_wake import (
    notify_item_scoped_qa_wait,
    stage_wait_idempotency_key,
)

from yoke_core.domain.work_claim_targets import make_item_target, make_steering_target


def _setup(conn, *, manual=True):
    plan_id = _seed(conn)
    if manual:
        _manual_plan(conn, plan_id)
    _project(conn)
    for session in (HOLDER_A, HOLDER_B, "group-steering", DRIVER_SESSION):
        seed_session(conn, session)
    for member, session in zip(MEMBERS[:2], (HOLDER_A, HOLDER_B)):
        _claim(
            conn,
            session_id=session,
            target_kind="item",
            scope_json=make_item_target(member).scope_json(),
        )
    _claim(
        conn,
        session_id="group-steering",
        target_kind="steering",
        scope_json=make_steering_target(1).scope_json(),
    )
    conn.execute(
        "UPDATE harness_sessions SET mode='parked' WHERE session_id=%s", (HOLDER_A,)
    )
    conn.commit()
    _form(conn)
    return run_groups(conn, RUN, "item-qa")[0]
