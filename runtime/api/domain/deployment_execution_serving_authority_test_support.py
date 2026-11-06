# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.fixtures.actor_roles import seed_project_role

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

from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    seed_roles_and_permissions,
)

from yoke_core.domain.actors import seed_human_actor

from yoke_core.domain.api_tokens import mint_token

from yoke_core.domain.db_helpers import iso8601_now

from yoke_core.domain.project_identity import resolve_project_id

from yoke_core.domain.sessions_lifecycle_claim import claim_work

from yoke_core.domain.work_claim_targets import make_item_target

from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

from yoke_core.domain.yoke_function_dispatch import dispatch

PROJECT = "externalwebapp"

FLOW = "external-hosted"

ITEM_ID = 9001


def _session(conn, actor_id: int, project_id: int, session_id: str) -> None:
    now = iso8601_now()
    conn.execute(
        "INSERT INTO harness_sessions "
        "(session_id,executor,provider,model,reasoning_effort,execution_level,workspace,project_id,"
        "mode,offered_at,last_heartbeat,actor_id) VALUES "
        "(%s,'codex','openai','gpt-6.1-sol','medium','primary',%s,%s,'wait',%s,%s,%s)",
        (session_id, f"/tmp/{session_id}", project_id, now, now, actor_id),
    )
    conn.commit()


def _project_owner(conn, project: str, session_id: str):
    project_id = resolve_project_id(conn, project)
    actor_id = seed_human_actor(conn, name=f"{project} owner")
    seed_project_role(
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
    public_ref: str | None = None,
    payload: dict | None = None,
):
    if run_id:
        target = {"kind": "workflow_run", "workflow_run_id": run_id}
    elif public_ref is not None:
        target = {"kind": "item", "public_ref": public_ref}
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
                {"name": "merged", "stage_kind": "execution", "step_runner": "auto"},
                {
                    "name": "approve-deploy",
                    "stage_kind": "execution",
                    "step_runner": "human-approval",
                },
                {
                    "name": "hosted-release",
                    "stage_kind": "execution",
                    "step_runner": "github-actions-workflow",
                    "workflow": "deploy.yml",
                },
                {"name": "complete", "stage_kind": "execution", "step_runner": "auto"},
            ]
        )
        conn.execute(
            "INSERT INTO deployment_flows "
            "(id,project_id,name,description,stages,on_failure,created_at,"
            "target_tier,status,definition_schema_version) VALUES "
            "(%s,%s,%s,'external delivery',%s,'halt',%s,'ephemeral','active',2)",
            (FLOW, project_id, FLOW, stages, iso8601_now()),
        )
        workflow_id, workflow_version_id = resolve_current_workflow_pin(conn, "issue")
        conn.execute(
            "INSERT INTO items "
            "(id,title,status,project_id,project_sequence,deployment_flow,"
            "workflow_id,workflow_version_id,created_at,updated_at) "
            "VALUES (%s,'external release','implemented',%s,1,%s,%s,%s,%s,%s)",
            (
                ITEM_ID,
                project_id,
                FLOW,
                workflow_id,
                workflow_version_id,
                iso8601_now(),
                iso8601_now(),
            ),
        )
        owner_session = "external-deploy-owner"
        owner_id, owner_token = _project_owner(
            conn,
            PROJECT,
            owner_session,
        )
        other_session = "yoke-only-owner"
        other_id, other_token = _project_owner(conn, "yoke", other_session)
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
                "owner_headers": {"Authorization": f"Bearer {owner_token.raw_token}"},
                "other_id": other_id,
                "other_session": other_session,
                "other_headers": {"Authorization": f"Bearer {other_token.raw_token}"},
            }


LINEAGE = "d" * 40
