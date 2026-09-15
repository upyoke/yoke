"""Project owners drive external deployments through serving authority."""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from runtime.api.fixtures import pg_testdb
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.api import app_factory
from yoke_core.domain import coordination_claims
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import mint_token
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.work_claim_targets import (
    make_deploy_serialization_target,
    make_item_target,
)
from yoke_core.domain.workflow_registry import resolve_current_workflow_pin
from yoke_core.domain.yoke_function_dispatch import dispatch


PROJECT = "externalwebapp"
FLOW = "external-hosted"
LINEAGE = "d" * 40
ITEM_ID = 9001


def _session(conn, actor_id: int, project_id: int, session_id: str) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,executor,provider,model,execution_lane,workspace,project_id,"
        "mode,offered_at,last_heartbeat,actor_id) VALUES "
        "(%s,'codex','openai','test','primary',%s,%s,'wait',%s,%s,%s)",
        (session_id, f"/tmp/{session_id}", project_id, now, now, actor_id),
    )
    conn.commit()


def _project_owner(conn, project: str, session_id: str):
    project_id = resolve_project_id(conn, project)
    actor_id = seed_human_actor(conn, name=f"{project} owner")
    grant_actor_project_role(
        conn,
        actor_id=actor_id,
        project_id=project_id,
        role_name=ROLE_OWNER,
        granted_by_actor_id=actor_id,
    )
    token = mint_token(
        conn,
        actor_id=actor_id,
        name=f"{project}-deployment-owner",
    )
    _session(conn, actor_id, project_id, session_id)
    return actor_id, token


def _call(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    function_id: str,
    *,
    run_id: str | None = None,
    item_id: int | None = None,
    payload: dict | None = None,
):
    if run_id:
        target = {"kind": "workflow_run", "workflow_run_id": run_id}
    elif item_id is not None:
        target = {"kind": "item", "item_id": item_id}
    else:
        target = {"kind": "global"}
    return client.post(
        "/v1/functions/call",
        headers=headers,
        json={
            "function": function_id,
            "version": "v1",
            "actor": {"actor_id": "discarded-at-http", "session_id": session_id},
            "target": target,
            "payload": payload or {},
            "preconditions": {},
            "options": {},
        },
    )


@pytest.fixture()
def serving_plane():
    with pg_testdb.test_database() as conn:
        seed_roles_and_permissions(conn)
        project_id = resolve_project_id(conn, PROJECT)
        stages = json.dumps(
            [
                {"name": "merged", "step_runner": "auto"},
                {"name": "approve-deploy", "step_runner": "human-approval"},
                {
                    "name": "hosted-release",
                    "step_runner": "github-actions-workflow",
                    "workflow": "deploy.yml",
                },
                {"name": "complete", "step_runner": "auto"},
            ]
        )
        conn.execute(
            "INSERT INTO deployment_flows "
            "(id,project_id,name,description,stages,on_failure,created_at,"
            "target_tier,status) VALUES "
            "(%s,%s,%s,'external delivery',%s,'halt',%s,'ephemeral','active')",
            (FLOW, project_id, FLOW, stages, iso8601_now()),
        )
        workflow_id, workflow_version_id = resolve_current_workflow_pin(
            conn, "issue"
        )
        conn.execute(
            "INSERT INTO items "
            "(id,title,status,project_id,project_sequence,deployment_flow,"
            "workflow_id,workflow_version_id,created_at,updated_at) "
            "VALUES (%s,'external release','implemented',%s,1,%s,%s,%s,%s,%s)",
            (
                ITEM_ID, project_id, FLOW, workflow_id, workflow_version_id,
                iso8601_now(), iso8601_now(),
            ),
        )
        owner_session = "external-deploy-owner"
        owner_id, owner_token = _project_owner(
            conn, PROJECT, owner_session,
        )
        other_session = "yoke-only-owner"
        other_id, other_token = _project_owner(conn, "yoke", other_session)
        coordination_claims.acquire(
            conn,
            make_deploy_serialization_target(project_id, PROJECT),
            owner_session,
            reason="external deployment test",
        )
        claim_work(
            conn,
            session_id=owner_session,
            target=make_item_target(ITEM_ID),
            reason="external item deployment test",
        )
        conn.commit()
        with TestClient(app_factory.create_app()) as client:
            yield {
                "client": client,
                "conn": conn,
                "owner_id": owner_id,
                "owner_session": owner_session,
                "owner_headers": {
                    "Authorization": f"Bearer {owner_token.raw_token}"
                },
                "other_id": other_id,
                "other_session": other_session,
                "other_headers": {
                    "Authorization": f"Bearer {other_token.raw_token}"
                },
            }


def test_project_only_owner_creates_pauses_resumes_fails_and_retries(
    serving_plane,
) -> None:
    client = serving_plane["client"]
    headers = serving_plane["owner_headers"]
    session_id = serving_plane["owner_session"]
    conn = serving_plane["conn"]
    actor_id = serving_plane["owner_id"]
    assert conn.execute(
        "SELECT COUNT(*) FROM actor_org_roles WHERE actor_id=%s", (actor_id,)
    ).fetchone()[0] == 0

    created = _call(
        client,
        headers,
        session_id,
        "deployment_runs.create",
        payload={"project": PROJECT, "flow": FLOW, "release_lineage": LINEAGE},
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["result"]["run_id"]

    started = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.update",
        run_id=run_id,
        payload={"field": "status", "value": "executing"},
    )
    assert started.status_code == 200, started.text
    paused = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.update",
        run_id=run_id,
        payload={"field": "current_stage", "value": "approve-deploy"},
    )
    assert paused.status_code == 200, paused.text
    context = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.context",
        run_id=run_id,
    )
    assert context.status_code == 200, context.text
    assert context.json()["result"]["run"]["current_stage"] == "approve-deploy"

    resumed = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.update",
        run_id=run_id,
        payload={"field": "current_stage", "value": "hosted-release"},
    )
    assert resumed.status_code == 200, resumed.text
    failed = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.update",
        run_id=run_id,
        payload={"field": "status", "value": "failed"},
    )
    assert failed.status_code == 200, failed.text

    retried = _call(
        client,
        headers,
        session_id,
        "deployment_runs.create",
        payload={"project": PROJECT, "flow": FLOW, "retry_of": run_id},
    )
    assert retried.status_code == 200, retried.text
    retry_id = retried.json()["result"]["run_id"]
    assert retry_id != run_id
    retry_context = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.context",
        run_id=retry_id,
    )
    assert retry_context.status_code == 200, retry_context.text
    retry_run = retry_context.json()["result"]["run"]
    assert retry_run["status"] == "created"
    assert retry_run["release_lineage"] == LINEAGE
    assert retry_context.json()["result"]["stages"][1]["name"] == "approve-deploy"
    qa_ready = _call(
        client,
        headers,
        session_id,
        "deployment_runs.execution.ephemeral_qa_ready",
        run_id=retry_id,
    )
    assert qa_ready.status_code == 200, qa_ready.text
    assert qa_ready.json()["result"]["ready"] is True

    local = dispatch(
        FunctionCallRequest(
            function="deployment_runs.execution.context",
            actor=ActorContext(actor_id=str(actor_id), session_id=session_id),
            target=TargetRef(kind="workflow_run", workflow_run_id=retry_id),
            payload={},
        ),
        ambient_session_id=session_id,
    )
    assert local.success is True
    assert local.result["run"]["id"] == retry_id


def test_project_only_owner_starts_item_bound_run_through_serving_handler(
    serving_plane,
) -> None:
    started = _call(
        serving_plane["client"],
        serving_plane["owner_headers"],
        serving_plane["owner_session"],
        "deployment_runs.start_for_item",
        item_id=ITEM_ID,
        payload={
            "project": PROJECT,
            "flow": FLOW,
            "release_lineage": LINEAGE,
        },
    )
    assert started.status_code == 200, started.text
    result = started.json()["result"]
    assert result["item_id"] == ITEM_ID
    assert result["project"] == PROJECT
    assert result["run_id"].startswith("run-")

    context = _call(
        serving_plane["client"],
        serving_plane["owner_headers"],
        serving_plane["owner_session"],
        "deployment_runs.execution.context",
        run_id=result["run_id"],
    )
    assert context.status_code == 200, context.text
    assert context.json()["result"]["members"][0]["item_id"] == ITEM_ID


def test_project_owner_cannot_drive_another_projects_run(serving_plane) -> None:
    created = _call(
        serving_plane["client"],
        serving_plane["owner_headers"],
        serving_plane["owner_session"],
        "deployment_runs.create",
        payload={"project": PROJECT, "flow": FLOW, "release_lineage": LINEAGE},
    )
    assert created.status_code == 200, created.text
    run_id = created.json()["result"]["run_id"]

    denied = _call(
        serving_plane["client"],
        serving_plane["other_headers"],
        serving_plane["other_session"],
        "deployment_runs.execution.context",
        run_id=run_id,
    )
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "permission_denied"
