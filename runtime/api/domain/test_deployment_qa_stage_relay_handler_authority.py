"""HTTP-boundary authority tests for the scoped-QA stage relay handlers.

Exercises ``deployment_runs.qa_stage.dispatch`` and ``.resume_refusals``
through the real ``/v1/functions/call`` boundary against a deployment flow
that declares real QA-gated stages — so the "nothing has passed yet" state
these tests assert on is a genuinely stored fact the handler must derive
from the run's own flow and database rows, not something either the test
or a caller hands it directly.
"""

from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from runtime.api.fixtures import pg_testdb
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
from yoke_core.domain.work_claim_targets import make_deploy_serialization_target


PROJECT = "externalwebapp"
FLOW = "external-scoped-qa-authority"
LINEAGE = "e" * 40
ITEM_QA_STAGE = "scoped-item-check"
RUN_QA_STAGE = "scoped-run-check"


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
    token = mint_token(conn, actor_id=actor_id, name=f"{project}-qa-stage-owner")
    _session(conn, actor_id, project_id, session_id)
    return actor_id, token


def _call(
    client: TestClient,
    headers: dict[str, str],
    session_id: str,
    function_id: str,
    *,
    run_id: str | None = None,
    payload: dict | None = None,
):
    target = (
        {"kind": "workflow_run", "workflow_run_id": run_id}
        if run_id
        else {"kind": "global"}
    )
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
def qa_stage_plane():
    with pg_testdb.test_database() as conn:
        seed_roles_and_permissions(conn)
        project_id = resolve_project_id(conn, PROJECT)
        stages = json.dumps(
            [
                {"name": "merged", "step_runner": "auto"},
                {
                    "name": ITEM_QA_STAGE,
                    "step_runner": "qa",
                    "stage_kind": "qa",
                    "scope": "item",
                },
                {
                    "name": RUN_QA_STAGE,
                    "step_runner": "qa",
                    "stage_kind": "qa",
                    "scope": "run",
                },
                {"name": "complete", "step_runner": "auto"},
            ]
        )
        conn.execute(
            "INSERT INTO deployment_flows "
            "(id,project_id,name,description,stages,on_failure,created_at,"
            "target_tier,status) VALUES "
            "(%s,%s,%s,'scoped QA authority test',%s,'halt',%s,'ephemeral','active')",
            (FLOW, project_id, FLOW, stages, iso8601_now()),
        )
        owner_session = "qa-stage-owner"
        owner_id, owner_token = _project_owner(conn, PROJECT, owner_session)
        # Same project, same admin role — the only difference from
        # owner_session is that this one never acquires the deploy lock,
        # so a refusal here is specifically the lock check, not authz.
        other_session = "qa-stage-no-lock"
        other_id, other_token = _project_owner(conn, PROJECT, other_session)
        coordination_claims.acquire(
            conn,
            make_deploy_serialization_target(project_id, PROJECT),
            owner_session,
            reason="scoped QA authority test",
        )
        conn.commit()
        with TestClient(app_factory.create_app()) as client:
            yield {
                "client": client,
                "conn": conn,
                "owner_session": owner_session,
                "owner_headers": {"Authorization": f"Bearer {owner_token.raw_token}"},
                "other_session": other_session,
                "other_headers": {"Authorization": f"Bearer {other_token.raw_token}"},
            }


def _create_run(plane) -> str:
    created = _call(
        plane["client"],
        plane["owner_headers"],
        plane["owner_session"],
        "deployment_runs.create",
        payload={"project": PROJECT, "flow": FLOW, "release_lineage": LINEAGE},
    )
    assert created.status_code == 200, created.text
    return created.json()["result"]["run_id"]


def test_dispatch_refuses_a_session_that_holds_no_deploy_lock(qa_stage_plane):
    run_id = _create_run(qa_stage_plane)

    response = _call(
        qa_stage_plane["client"],
        qa_stage_plane["other_headers"],
        qa_stage_plane["other_session"],
        "deployment_runs.qa_stage.dispatch",
        run_id=run_id,
        payload={"stage_name": ITEM_QA_STAGE},
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "deploy_lock_required"


def test_resume_refusals_refuses_a_session_that_holds_no_deploy_lock(qa_stage_plane):
    run_id = _create_run(qa_stage_plane)

    response = _call(
        qa_stage_plane["client"],
        qa_stage_plane["other_headers"],
        qa_stage_plane["other_session"],
        "deployment_runs.qa_stage.resume_refusals",
        run_id=run_id,
        payload={"start_stage": "complete"},
    )
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "deploy_lock_required"


def test_dispatch_derives_the_stage_scope_from_the_stored_flow_not_the_caller(
    qa_stage_plane,
):
    """Only a stage name crosses the wire; the scope is a stored server fact.

    The request carries nothing about scope at all. An "item-scoped QA
    stage has no attached run members" verdict can only come from the
    handler having looked up ``scope: "item"`` on its own, against the
    run's real stored flow, for a run created with no attached items.
    """
    run_id = _create_run(qa_stage_plane)

    response = _call(
        qa_stage_plane["client"],
        qa_stage_plane["owner_headers"],
        qa_stage_plane["owner_session"],
        "deployment_runs.qa_stage.dispatch",
        run_id=run_id,
        payload={"stage_name": ITEM_QA_STAGE},
    )
    assert response.status_code == 200, response.text
    result = response.json()["result"]
    assert result["code"] == 1
    assert "item-scoped QA stage has no attached run members" in result["message"]


def test_dispatch_refuses_a_stage_name_the_stored_flow_never_declared(qa_stage_plane):
    """A fabricated stage name cannot be dispatched — there is no scope to invent."""
    run_id = _create_run(qa_stage_plane)

    response = _call(
        qa_stage_plane["client"],
        qa_stage_plane["owner_headers"],
        qa_stage_plane["owner_session"],
        "deployment_runs.qa_stage.dispatch",
        run_id=run_id,
        payload={"stage_name": "not-a-real-stage"},
    )
    assert response.status_code == 404, response.text
    assert response.json()["error"]["code"] == "not_found"


def test_resume_refusals_reflect_a_genuinely_unresolved_stored_qa_gate(qa_stage_plane):
    """The refusal comes from real absent qa_requirements rows, not a fixture.

    Nothing seeds a qa_requirements row for this run — the run's own stored
    flow already declares a QA stage ahead of "complete", so the absence of
    any acceptance record for it is itself the genuine, currently-unresolved
    gate a resume must not silently skip.
    """
    run_id = _create_run(qa_stage_plane)

    response = _call(
        qa_stage_plane["client"],
        qa_stage_plane["owner_headers"],
        qa_stage_plane["owner_session"],
        "deployment_runs.qa_stage.resume_refusals",
        run_id=run_id,
        payload={"start_stage": "complete"},
    )
    assert response.status_code == 200, response.text
    message = response.json()["result"]["message"]
    assert RUN_QA_STAGE in message
    assert "0 current acceptance records" in message


def test_resume_refusals_ignore_a_caller_supplied_stage_list(qa_stage_plane):
    """A caller-supplied (here: emptied) stage list must not produce a false clear."""
    run_id = _create_run(qa_stage_plane)

    response = _call(
        qa_stage_plane["client"],
        qa_stage_plane["owner_headers"],
        qa_stage_plane["owner_session"],
        "deployment_runs.qa_stage.resume_refusals",
        run_id=run_id,
        payload={"start_stage": "complete", "stages": []},
    )
    assert response.status_code == 200, response.text
    message = response.json()["result"]["message"]
    assert RUN_QA_STAGE in message


def test_resume_refusals_request_schema_has_no_client_supplied_stage_list():
    from yoke_core.domain.handlers import deployment_qa_stage_relay as relay

    assert "stages" not in relay.DeploymentQaStageResumeRefusalsRequest.model_fields


def test_dispatch_request_schema_has_no_client_supplied_stage_config():
    from yoke_core.domain.handlers import deployment_qa_stage_relay as relay

    assert "stage" not in relay.DeploymentQaStageDispatchRequest.model_fields
