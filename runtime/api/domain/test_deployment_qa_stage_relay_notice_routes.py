"""The registered relay entrypoint really sends both notices.

``test_deployment_qa_stage_dispatch_wake.py`` and
``..._dispatch_result_report.py`` drive the server-side function directly,
which proves the routing but not that the registered path reaches it: the
relay handler resolves the run, takes the deploy lock, re-derives the
stage from the run's own stored flow, and only then calls it. A wake that
works when called directly and never fires through
``deployment_runs.qa_stage.dispatch`` would look healthy in those files
and deliver nothing in production.

So these cases go through ``handle_deployment_qa_stage_dispatch`` with a
real request, a real deploy lock, a real claim holder and a real item
owner, and assert the rows that actually reach people.
"""

from __future__ import annotations

import json
from typing import Any
from unittest import mock

from runtime.api.domain.coordination_claim_test_support import (
    PROJECT_YOKE,
    seed_project,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    HOLDER_A,
    SESSION_ACTOR_ID,
    _claim,
    _project,
    _recipients,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import coordination_claims
from yoke_core.domain.deployment_qa_stage_wake import stage_wait_idempotency_key
from yoke_core.domain.handlers import deployment_qa_stage_relay as relay
from yoke_core.domain.work_claim_targets import (
    make_deploy_serialization_target,
    make_item_target,
)

DRIVER_SESSION = "relay-driver-session"
RUN_ID = "run-relay-notice"
ITEM_ID = 9640
STAGE = "item-qa"


def _flow_stages() -> str:
    return json.dumps(
        [
            {
                "name": "deploy",
                "step_runner": "health-check",
                "stage_kind": "execution",
                "scope": "run",
            },
            {
                "name": STAGE,
                "step_runner": "qa",
                "stage_kind": "qa",
                "scope": "item",
                "target": {
                    "kind": "persistent_environment",
                    "environment": "stage",
                    "source_stage": "deploy",
                },
                "verdict": {"mode": "agent_only"},
                "notification": {
                    "enabled": True,
                    "recipients": {"item_owners": True},
                },
            },
        ]
    )


def _seed(conn: Any) -> None:
    _project(conn)
    seed_project(conn, PROJECT_YOKE, "yoke")
    conn.execute(
        "INSERT INTO deployment_flows(id,project_id,name,description,stages,"
        "on_failure,created_at,definition_schema_version,status) VALUES "
        "('flow-relay-notice',1,'flow-relay-notice','',%s,'halt',%s,2,'disabled')",
        (_flow_stages(), "2026-09-14T00:00:00Z"),
    )
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "current_stage,created_at) VALUES (%s,1,'flow-relay-notice',%s,'executing',"
        "%s,%s)",
        (RUN_ID, "a" * 40, STAGE, "2026-09-14T00:00:00Z"),
    )
    # The member item, its owner, and the agent session holding its claim.
    insert_item(
        conn,
        id=ITEM_ID,
        project_sequence=ITEM_ID,
        workflow_id="issue",
        owner=str(SESSION_ACTOR_ID),
    )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES (%s,%s,%s)",
        (RUN_ID, ITEM_ID, "2026-09-14T00:00:00Z"),
    )
    from yoke_core.domain.actor_permissions import ROLE_ADMIN, grant_actor_org_role

    for row in conn.execute("SELECT org_id FROM projects WHERE id=1").fetchall():
        if row["org_id"] is not None:
            grant_actor_org_role(
                conn,
                actor_id=SESSION_ACTOR_ID,
                org_id=int(row["org_id"]),
                role_name=ROLE_ADMIN,
            )
    conn.commit()
    seed_session(conn, HOLDER_A)
    _claim(
        conn,
        session_id=HOLDER_A,
        target_kind="item",
        scope_json=make_item_target(ITEM_ID).scope_json(),
    )
    # The driver session holds the project's deploy lock, which the relay
    # handler requires before it will evaluate anything.
    seed_session(conn, DRIVER_SESSION)
    coordination_claims.acquire(
        conn,
        make_deploy_serialization_target(PROJECT_YOKE, "yoke"),
        DRIVER_SESSION,
        reason="relay notice route test",
    )
    conn.commit()


def _request() -> FunctionCallRequest:
    return FunctionCallRequest(
        function=relay.DISPATCH_FUNCTION_ID,
        actor=ActorContext(
            actor_id=str(SESSION_ACTOR_ID), session_id=DRIVER_SESSION
        ),
        target=TargetRef(kind="workflow_run", workflow_run_id=RUN_ID),
        payload={"stage_name": STAGE},
    )


def _status(outcome: str, *, accepted: bool, reasons=()):
    return {
        "accepted": accepted,
        "outcome": outcome,
        "reasons": list(reasons),
        "request_id": None,
        "target_digest": "digest-relay",
    }


def test_a_waiting_stage_wakes_the_holder_through_the_registered_path(
    test_db: Any,
) -> None:
    _seed(test_db)

    with (
        mock.patch(
            "yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status",
            return_value=_status(
                "waiting", accepted=False, reasons=["awaiting agent verdict"]
            ),
        ),
        mock.patch(
            "yoke_core.domain.deployment_qa_stage_materialization"
            ".materialize_deployment_qa_stage"
        ),
    ):
        outcome = relay.handle_deployment_qa_stage_dispatch(_request())

    assert outcome.primary_success is True, outcome.error
    assert int(outcome.result_payload["code"]) == -4
    assert "awaiting agent verdict" in outcome.result_payload["message"]
    # The wake reached the item's claim holder, through the relay.
    key = stage_wait_idempotency_key(RUN_ID, STAGE, ITEM_ID, "digest-relay")
    assert _recipients(test_db, key) == [HOLDER_A]


def test_a_settled_stage_reports_its_result_through_the_registered_path(
    test_db: Any,
) -> None:
    _seed(test_db)

    with (
        mock.patch(
            "yoke_core.domain.deployment_qa_stage_gate.deployment_qa_stage_status",
            return_value=_status("passed", accepted=True),
        ),
        mock.patch(
            "yoke_core.domain.deployment_qa_stage_materialization"
            ".materialize_deployment_qa_stage"
        ),
    ):
        outcome = relay.handle_deployment_qa_stage_dispatch(_request())

    assert outcome.primary_success is True, outcome.error
    assert int(outcome.result_payload["code"]) == 0
    # The configured audience — the item's owner — got an Inbox row.
    rows = test_db.execute(
        "SELECT r.actor_id FROM session_messages m "
        "JOIN actor_message_recipients r ON r.message_id = m.message_id "
        "WHERE m.idempotency_key LIKE %s",
        ("deployment-qa-stage-result:%",),
    ).fetchall()
    assert [int(row["actor_id"]) for row in rows] == [SESSION_ACTOR_ID]


def test_the_relay_refuses_a_stage_the_runs_own_flow_does_not_declare(
    test_db: Any,
) -> None:
    """The caller's stage name is data, re-derived from the stored flow."""
    _seed(test_db)
    request = FunctionCallRequest(
        function=relay.DISPATCH_FUNCTION_ID,
        actor=ActorContext(
            actor_id=str(SESSION_ACTOR_ID), session_id=DRIVER_SESSION
        ),
        target=TargetRef(kind="workflow_run", workflow_run_id=RUN_ID),
        payload={"stage_name": "a-stage-nobody-declared"},
    )

    outcome = relay.handle_deployment_qa_stage_dispatch(request)

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert "has no stage named" in outcome.error.message


def test_the_relay_refuses_without_the_deploy_lock(test_db: Any) -> None:
    _seed(test_db)
    claim = coordination_claims.active_claim(
        test_db, make_deploy_serialization_target(PROJECT_YOKE, "yoke")
    )
    assert claim is not None
    coordination_claims.release(
        test_db, claim.id, "relay notice route test teardown"
    )
    test_db.commit()

    outcome = relay.handle_deployment_qa_stage_dispatch(_request())

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "deploy_lock_required"
