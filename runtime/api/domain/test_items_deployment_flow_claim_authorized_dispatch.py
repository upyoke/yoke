"""``items.deployment_flow.claim_default`` through the real dispatch route.

A direct handler call proves the conditional UPDATE; it proves nothing
about the claim-required guardrail or project-visibility permission the
registered function id declares. This exercises both through the actual
authenticated HTTP function-call route, the same shape any real caller
(the done-transition guard included) reaches this function through.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from runtime.api.fixtures import pg_testdb
from yoke_core.api import app_factory
from yoke_core.domain.actor_permissions import (
    ROLE_OWNER,
    ROLE_VIEWER,
    grant_actor_project_role,
    seed_roles_and_permissions,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.api_tokens import mint_token
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.sessions_lifecycle_claim import claim_work
from yoke_core.domain.work_claim_targets import make_item_target
from yoke_core.domain.workflow_registry import resolve_current_workflow_pin

PROJECT = "yoke"
FLOW = "claim-default-test-flow"
ITEM_ID = 9905


def _call(client: TestClient, headers: dict, session_id: str, payload: dict):
    return client.post(
        "/v1/functions/call",
        headers=headers,
        json={
            "function": "items.deployment_flow.claim_default",
            "version": "v1",
            "actor": {"actor_id": "discarded-at-http", "session_id": session_id},
            "target": {"kind": "item", "item_id": ITEM_ID},
            "payload": payload,
            "preconditions": {},
            "options": {},
        },
    )


@pytest.fixture()
def claim_plane():
    with pg_testdb.test_database() as conn:
        seed_roles_and_permissions(conn)
        project_id = resolve_project_id(conn, PROJECT)
        conn.execute(
            "INSERT INTO deployment_flows "
            "(id,project_id,name,description,stages,on_failure,created_at,"
            "target_tier,status) VALUES "
            "(%s,%s,%s,'test flow','[]','halt',%s,'ephemeral','active')",
            (FLOW, project_id, FLOW, iso8601_now()),
        )
        workflow_id, workflow_version_id = resolve_current_workflow_pin(conn, "issue")
        conn.execute(
            "INSERT INTO items "
            "(id,title,status,project_id,project_sequence,"
            "workflow_id,workflow_version_id,created_at,updated_at) "
            "VALUES (%s,'claim-default target','implementing',%s,1,%s,%s,%s,%s)",
            (
                ITEM_ID, project_id, workflow_id, workflow_version_id,
                iso8601_now(), iso8601_now(),
            ),
        )
        owner_actor_id = seed_human_actor(conn, name="claim-default owner")
        grant_actor_project_role(
            conn,
            actor_id=owner_actor_id,
            project_id=project_id,
            role_name=ROLE_OWNER,
            granted_by_actor_id=owner_actor_id,
        )
        owner_token = mint_token(
            conn, actor_id=owner_actor_id, name="claim-default-owner",
        )
        owner_session = "claim-default-owner-session"
        now = iso8601_now()
        conn.execute(
            "INSERT INTO harness_sessions "
            "(session_id,executor,provider,model,execution_lane,workspace,"
            "project_id,mode,offered_at,last_heartbeat,actor_id) VALUES "
            "(%s,'codex','openai','test','primary','/tmp/claim-default',%s,"
            "'wait',%s,%s,%s)",
            (owner_session, project_id, now, now, owner_actor_id),
        )
        claim_work(
            conn,
            session_id=owner_session,
            target=make_item_target(ITEM_ID),
            reason="claim-default authorized-dispatch test",
        )
        other_actor_id = seed_human_actor(conn, name="claim-default outsider")
        grant_actor_project_role(
            conn,
            actor_id=other_actor_id,
            project_id=project_id,
            role_name=ROLE_VIEWER,
            granted_by_actor_id=owner_actor_id,
        )
        other_token = mint_token(
            conn, actor_id=other_actor_id, name="claim-default-outsider",
        )
        other_session = "claim-default-outsider-session"
        conn.execute(
            "INSERT INTO harness_sessions "
            "(session_id,executor,provider,model,execution_lane,workspace,"
            "project_id,mode,offered_at,last_heartbeat,actor_id) VALUES "
            "(%s,'codex','openai','test','primary','/tmp/claim-default-2',%s,"
            "'wait',%s,%s,%s)",
            (other_session, project_id, now, now, other_actor_id),
        )
        conn.commit()
        with TestClient(app_factory.create_app()) as client:
            yield {
                "client": client,
                "owner_session": owner_session,
                "owner_headers": {"Authorization": f"Bearer {owner_token.raw_token}"},
                "other_session": other_session,
                "other_headers": {"Authorization": f"Bearer {other_token.raw_token}"},
            }


def test_the_items_claim_holder_can_claim_the_default_flow(claim_plane) -> None:
    response = _call(
        claim_plane["client"],
        claim_plane["owner_headers"],
        claim_plane["owner_session"],
        {"flow_id": FLOW},
    )
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["success"] is True
    assert body["result"]["claimed"] is True
    assert body["result"]["deployment_flow"] == FLOW


def test_a_session_without_the_items_claim_is_refused(claim_plane) -> None:
    response = _call(
        claim_plane["client"],
        claim_plane["other_headers"],
        claim_plane["other_session"],
        {"flow_id": FLOW},
    )
    assert response.status_code == 409, response.text
    body = response.json()
    assert body["success"] is False
    assert body["error"]["code"] == "claim_required"
