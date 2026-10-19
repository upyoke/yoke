"""Retired machine decisions remain readable without actions or storage changes."""

import json

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_contracts.timestamps import parse_instant
from yoke_core.domain.actor_permissions import grant_actor_project_role
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.decision_requests import create_decision_request
from yoke_core.domain.org_schema import seed_default_org
from yoke_core.domain.project_identity import resolve_project_id
from yoke_core.domain.project_seed_test_helpers import seed_project_identities
from yoke_core.domain.yoke_function_dispatch import dispatch


@pytest.mark.parametrize("status", ["pending", "resolved", "withdrawn"])
def test_historical_machine_request_is_read_only_and_absent_from_inbox(test_db, status):
    seed_project_identities(test_db)
    actor_id = seed_human_actor(test_db, "Historical requester")
    project_id = resolve_project_id(test_db, "yoke")
    grant_actor_project_role(
        test_db,
        actor_id=actor_id,
        project_id=project_id,
        role_name="viewer",
    )
    org_id = seed_default_org(test_db)
    stamp = parse_instant("2026-01-01T00:00:00Z")
    request_id = test_db.execute(
        "INSERT INTO decision_requests "
        "(kind,subject_type,subject_key,subject_context,org_id,originator_actor_id,"
        "status,created_at,resolved_at,withdrawn_at,resolution_action) "
        "VALUES ('machine_approval','machine_auth_request',%s,%s,%s,%s,%s,%s,%s,%s,%s) "
        "RETURNING id",
        (
            "historical-device",
            json.dumps({"expires_at": "2026-01-01T00:10:00Z"}),
            org_id,
            actor_id,
            status,
            stamp,
            stamp if status == "resolved" else None,
            stamp if status == "withdrawn" else None,
            "approve" if status == "resolved" else None,
        ),
    ).fetchone()[0]
    test_db.execute(
        "INSERT INTO decision_request_actor_authorities VALUES (%s,%s)",
        (request_id, actor_id),
    )
    if status == "resolved":
        test_db.execute(
            "INSERT INTO decision_request_decisions (request_id,actor_id,action,decided_at) "
            "VALUES (%s,%s,'approve',%s)",
            (request_id, actor_id, stamp),
        )
    test_db.commit()

    def stored():
        return [
            [tuple(row) for row in test_db.execute(sql, (request_id,)).fetchall()]
            for sql in (
                "SELECT * FROM decision_requests WHERE id=%s",
                "SELECT * FROM decision_request_actor_authorities WHERE request_id=%s",
                "SELECT * FROM decision_request_decisions WHERE request_id=%s",
            )
        ]

    def call(function, payload):
        return dispatch(
            FunctionCallRequest(
                function=function,
                target=TargetRef(kind="global"),
                actor=ActorContext(actor_id=str(actor_id), session_id=""),
                payload=payload,
            ),
            ambient_session_id="",
        )

    original = stored()
    inbox = call("inbox.list", {})
    assert inbox.success, inbox.error
    assert "machine_approvals" not in inbox.result
    assert all(
        row["kind"] != "machine_approval" for row in inbox.result["needs_decision"]
    )
    assert stored() == original

    detail = call("decision_requests.get", {"request_id": request_id})
    assert detail.success, detail.error
    assert detail.result["request"]["status"] == status
    assert detail.result["request"]["actions"] == []
    assert detail.result["request"]["subject_type"] == "machine_auth_request"
    assert stored() == original

    refused = call(
        "decision_requests.resolve", {"request_id": request_id, "action": "approve"}
    )
    assert not refused.success
    assert refused.error.code == "invalid_state"
    assert stored() == original

    with pytest.raises(ValueError, match="unknown decision request kind"):
        create_decision_request(
            test_db,
            kind="machine_approval",
            subject_type="machine_auth_request",
            subject_key="new-device",
            org_id=org_id,
            named_actor_ids=[actor_id],
        )
    assert stored() == original
