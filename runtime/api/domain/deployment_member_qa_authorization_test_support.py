"""Shared frozen mixed-release subject for QA authorization tests."""

from __future__ import annotations

from types import SimpleNamespace

from runtime.api.fixtures.backlog_insert_support import ensure_project_id
from runtime.api.fixtures.bound_source_release import (
    CONSUMER_PROJECT,
    SEEDED_AT,
    stages_with_item_qa,
    two_project_release,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import create_smoke_plan
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.deployment_run_bound_sources import record_bound_sources
from yoke_core.domain.deployment_run_carried_membership import enroll_carried_members
from yoke_core.domain.deployment_run_composition_freeze import freeze_run_composition
from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
)

RUN = "run-candidate"
STAGE = "item-qa"


def _request(
    function: str,
    *,
    member: str | None = None,
    execution_id: str | None = None,
    project: str | None = CONSUMER_PROJECT,
    requirement_id: int | None = None,
):
    target = (
        TargetRef(
            kind="qa_requirement", qa_requirement_id=requirement_id, project_id=project
        )
        if requirement_id is not None
        else TargetRef(kind="deployment_run", deployment_run_id=RUN, project_id=project)
    )
    payload = (
        {"execution_id": execution_id}
        if execution_id
        else (
            {"deployment_stage": STAGE, "deployment_member": member} if member else {}
        )
    )
    if function == "qa.plan.materialize":
        payload["plan"] = "consumer-smoke"
        payload["project"] = project
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="1", session_id="consumer-qa"),
        target=target,
        payload=payload,
    )


def _entry(function: str):
    return SimpleNamespace(
        function_id=function, side_effects=("qa_write",), version="v1"
    )


def _mixed_run(conn, tmp_path, monkeypatch):
    consumer_id = ensure_project_id(conn, CONSUMER_PROJECT, ts=SEEDED_AT)
    conn.execute(
        "UPDATE projects SET public_item_prefix='CNS' WHERE id=%s",
        (consumer_id,),
    )
    conn.commit()
    release = two_project_release(
        conn, tmp_path, monkeypatch, stages=stages_with_item_qa()
    )
    record_bound_sources(conn, RUN)
    enroll_carried_members(conn, RUN)
    freeze_run_composition(conn, RUN)
    conn.execute(
        "UPDATE deployment_runs SET status='executing', current_stage='hosted-release' "
        "WHERE id=%s",
        (RUN,),
    )
    receipt = allocate_deployment_stage_receipt(
        conn,
        run_id=RUN,
        stage_name="hosted-release",
        correlation_id="consumer-release",
        target_kind="persistent_environment",
        executor="test",
        commit=False,
    )
    complete_deployment_stage_receipt(
        conn,
        run_id=RUN,
        receipt_id=int(receipt["id"]),
        correlation_id=str(receipt["correlation_id"]),
        status="ready",
        target_name="stage",
        observed_url="https://preview.example.test",
        observed_release_lineage=str(
            conn.execute(
                "SELECT release_lineage FROM deployment_runs WHERE id=%s", (RUN,)
            ).fetchone()[0]
        ),
        executor_receipt="test://ready",
        commit=False,
    )
    conn.execute(
        "UPDATE deployment_runs SET current_stage=%s WHERE id=%s", (STAGE, RUN)
    )
    conn.commit()
    create_smoke_plan(conn, project=CONSUMER_PROJECT, slug="consumer-smoke")
    return release


def _consumer_actor(conn, project_id: int) -> int:
    seed_roles_and_permissions(conn)
    actor_id = int(
        conn.execute(
            "INSERT INTO actors(kind,created_at) VALUES('human', '2026-09-01T00:00:00Z') "
            "RETURNING id"
        ).fetchone()[0]
    )
    grant_actor_project_role(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        role_name=ROLE_OWNER,
        granted_by_actor_id=actor_id,
    )
    conn.commit()
    return actor_id
