# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from unittest import mock

from uuid import uuid4

import pytest

import psycopg

from runtime.api.domain.machine_qa_session_seed import seed_qa_session

from runtime.api.domain.deployment_qa_stage_member_removal_test_support import (
    REMOVED,
    REMAINING,
    RUN,
    _ready_run,
)

from runtime.api.domain.qa_host_turns_test_support import _notices

from runtime.api.domain.deployment_member_qa_authorization_test_support import _entry

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from yoke_core.domain.coordination_claims import acquire, active_claim, release

from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)

from yoke_core.domain.deployment_run_member_removal import remove_member_on

from yoke_core.domain.deployment_run_membership_removals import (
    record_membership_removals,
)

from yoke_core.domain.handlers.qa_plan_execution import handle_plan_execution_abort

from yoke_core.domain.qa_deployment_function_subject import resolve_run_qa_subject

from yoke_core.domain.qa_execution_request_identity import resolve_execution_request

from yoke_core.domain.qa_host_turns import (
    host_line,
    join_host_line,
    reserve_host_turn,
)

from yoke_core.domain.qa_plan_execution_store import roster_digest

from yoke_core.domain.qa_plan_execution_state import begin_plan_execution

from yoke_core.domain.deployment_runs_lock import lock_run

from yoke_core.domain.workflow_item_binding_lock import lock_item_workflow_bindings

from runtime.api.fixtures.pg_testdb import connect_test_database

from yoke_core.domain.work_claim_targets import make_qa_admission_target

from yoke_core.domain.yoke_function_dispatch_qa_claims import qa_subject_claim_verdict

from yoke_core.domain.yoke_function_permissions import check_dispatch_permission


def _execution(
    conn, *, member=REMOVED, state="waiting", stage="item-qa", session="removed-qa"
):
    execution = str(uuid4())
    conn.execute(
        "INSERT INTO qa_plan_executions(id,deployment_run_id,deployment_stage,"
        "deployment_member_item_id,session_id,actor_id,roster_digest,roster_json,"
        "cursor_ordinal,state,created_at,heartbeat_at) "
        "VALUES(%s,%s,%s,%s,%s,'1',%s,'[]',0,%s,%s,%s)",
        (
            execution,
            RUN,
            stage,
            member,
            session,
            roster_digest([]),
            state,
            "2026-10-01T10:00:00Z",
            "2026-10-01T10:00:00Z",
        ),
    )
    if state == "waiting":
        join_host_line(
            conn,
            make_qa_admission_target("linux-lab"),
            session_id=session,
            actor_id=1,
            resume_command="resume QA",
            execution_id=execution,
        )
    conn.commit()
    return execution


def _request(execution, *, function="qa.plan_execution.abort", session="removed-qa"):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="1", session_id=session),
        target=TargetRef(kind="global", project_id="yoke"),
        payload={"execution_id": execution, "reason": "removed member residue"},
    )
