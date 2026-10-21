"""An execution request resolves its QA subject once, and its cost is linear.

Permission, claim verification, the handler's target check and settlement
all need the run/stage/member subject behind one execution. Each resolution
walks the run's members to find one that attaches the shared plan, so a
request that resolved it four times did four times that work. These dispatch
real check-ins against a shared execution in runs of growing size.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any
from unittest import mock

from runtime.api.domain.test_deployment_qa_stage_execution import (
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
from yoke_core.domain import deployment_qa_shared_plans, qa_deployment_function_subject
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
)
from yoke_core.domain.yoke_function_dispatch import dispatch

SESSION = "subject-once-session"
STAGE = "item-qa"


def _shared_execution(conn: Any, run_id: str, members: tuple[int, ...]) -> dict:
    plan_id = _plan(conn, f"shared-{run_id}")
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
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=members[-1],
    )
    actor_id = register_session_actor(conn, SESSION)
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage=STAGE,
        deployment_member_item_id=members[-1],
        actor_id=str(actor_id),
        session_id=SESSION,
    )
    assert execution["deployment_member_item_id"] is None
    return execution


def _advance_every_case(conn: Any, execution: dict) -> None:
    from yoke_core.domain.qa_requirement_pass_currency import (
        stamp_executed_method_config,
    )

    now = "2026-09-14T00:02:00Z"
    for ordinal, case in enumerate(execution["roster"]):
        requirement_id = int(case["requirement_id"])
        config = conn.execute(
            "SELECT method_config FROM qa_requirements WHERE id=%s", (requirement_id,)
        ).fetchone()[0]
        raw = stamp_executed_method_config(
            "shared case passed", config, conn=conn, requirement_id=requirement_id
        )
        run_id = conn.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
            "raw_result,started_at,completed_at,created_at) VALUES "
            "(%s,'worktree_run','plan_case','pass',%s,%s,%s,%s) RETURNING id",
            (requirement_id, raw, now, now, now),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
            "artifact_handle,created_at) VALUES (%s,'log','application/json',%s,%s)",
            (run_id, "evidence://shared-case", now),
        )
        advance_plan_execution(
            conn,
            execution,
            ordinal=ordinal,
            requirement_id=requirement_id,
            result={
                "requirement_id": requirement_id,
                "verdict": "pass",
                "case_outcome": "passed",
                "run_id": int(run_id),
            },
        )
    conn.commit()


def _requests(execution: dict) -> list[tuple[str, dict]]:
    pause = {
        "phase": "checkin",
        "cursor": len(execution["roster"]),
        "request_id": "pause-receipt",
        "attempts": [],
    }
    return [
        ("qa.plan_execution.heartbeat", {}),
        ("qa.plan_execution.pause", pause),
        ("qa.plan_execution.complete", {}),
    ]


def _dispatch(run_id: str, execution: dict, function: str, payload: dict) -> None:
    actor_id = str(execution["actor_id"])
    response = dispatch(
        FunctionCallRequest(
            function=function,
            actor=ActorContext(actor_id=actor_id, session_id=SESSION),
            target=TargetRef(
                kind="deployment_run", deployment_run_id=run_id, project_id="yoke"
            ),
            payload={"execution_id": str(execution["id"]), **payload},
        )
    )
    assert response.success, (function, response.error)


@contextmanager
def _statements() -> Iterator[list[int]]:
    import psycopg

    counted = [0]
    execute = psycopg.Cursor.execute

    def counting(cursor, *args, **kwargs):
        counted[0] += 1
        return execute(cursor, *args, **kwargs)

    with mock.patch.object(psycopg.Cursor, "execute", counting):
        yield counted


def _request_statements(conn: Any, run_id: str, size: int) -> dict[str, int]:
    first = 9500 + 100 * (size // 10)
    members = tuple(range(first, first + size))
    execution = _shared_execution(conn, run_id, members)
    _advance_every_case(conn, execution)
    counts = {}
    for function, payload in _requests(execution):
        with _statements() as counted:
            _dispatch(run_id, execution, function, payload)
        counts[function] = counted[0]
    return counts


def test_each_execution_request_resolves_its_subject_once(test_db):
    run_id = "run-subject-once"
    execution = _shared_execution(test_db, run_id, (9401, 9402, 9403))
    _advance_every_case(test_db, execution)
    for function, payload in _requests(execution):
        with (
            mock.patch.object(
                deployment_qa_shared_plans,
                "_read_execution_subject",
                wraps=deployment_qa_shared_plans._read_execution_subject,
            ) as execution_reads,
            mock.patch.object(
                qa_deployment_function_subject,
                "_resolve_run_qa_subject",
                wraps=qa_deployment_function_subject._resolve_run_qa_subject,
            ) as run_reads,
        ):
            _dispatch(run_id, execution, function, payload)
        assert run_reads.call_count == 1, function
        assert execution_reads.call_count == 1, function


def test_execution_request_statements_grow_at_most_linearly(test_db):
    sizes = (10, 20, 40)
    counts = [
        _request_statements(test_db, f"run-subject-linear-{size}", size)
        for size in sizes
    ]
    for function in counts[0]:
        small, middle, large = (count[function] for count in counts)
        # Linear cost adds the same statements per doubling step at most
        # twice over; quadratic cost would add four times as many.
        assert large - middle <= 2 * (middle - small) + 10, (
            function,
            small,
            middle,
            large,
        )
