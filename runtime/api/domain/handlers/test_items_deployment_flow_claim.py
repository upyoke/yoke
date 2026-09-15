"""``items.deployment_flow.claim_default`` claims the field exactly once.

Exercises the actual conditional ``UPDATE ... WHERE deployment_flow IS
NULL OR deployment_flow=''`` against a real database, not a mocked
rowcount -- the same claim-once idiom
``session_launch_registered_session_binding.adopt_attested_session_identity``
already uses for a different field.
"""

from __future__ import annotations

from typing import Any

from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.handlers.items_deployment_flow_claim import (
    handle_claim_default_deployment_flow,
)


def _flow(conn: Any, flow_id: str, project_id: int = 1) -> None:
    conn.execute(
        "INSERT INTO deployment_flows (id,project_id,name,stages,created_at) "
        "VALUES (%s,%s,%s,'[]','2026-09-15T00:00:00Z')",
        (flow_id, project_id, flow_id),
    )
    conn.commit()


def _request(item_id: int, flow_id: str) -> FunctionCallRequest:
    return FunctionCallRequest(
        function="items.deployment_flow.claim_default",
        actor=ActorContext(session_id="sess-claim-test"),
        target=TargetRef(kind="item", item_id=item_id),
        payload={"flow_id": flow_id},
    )


def test_claims_an_empty_field(test_db: Any) -> None:
    item_id = 9901
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    _flow(test_db, "flow-a")

    outcome = handle_claim_default_deployment_flow(_request(item_id, "flow-a"))

    assert outcome.primary_success is True
    assert outcome.result_payload["claimed"] is True
    assert outcome.result_payload["deployment_flow"] == "flow-a"
    row = test_db.execute(
        "SELECT deployment_flow FROM items WHERE id=%s", (item_id,)
    ).fetchone()
    assert row["deployment_flow"] == "flow-a"


def test_does_not_overwrite_a_value_already_set(test_db: Any) -> None:
    item_id = 9902
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    _flow(test_db, "flow-a")
    _flow(test_db, "flow-b")
    test_db.execute(
        "UPDATE items SET deployment_flow=%s WHERE id=%s", ("flow-b", item_id)
    )
    test_db.commit()

    outcome = handle_claim_default_deployment_flow(_request(item_id, "flow-a"))

    assert outcome.primary_success is True
    assert outcome.result_payload["claimed"] is False
    assert outcome.result_payload["deployment_flow"] == "flow-b"
    row = test_db.execute(
        "SELECT deployment_flow FROM items WHERE id=%s", (item_id,)
    ).fetchone()
    assert row["deployment_flow"] == "flow-b"


def test_a_second_racing_claim_after_the_first_commits_loses(test_db: Any) -> None:
    """Two sequential claim_default calls for the same item: the first
    genuinely claims it, and the second -- reflecting what a concurrent
    request from the same claim holder would see once the first's
    transaction commits -- sees the field already set and does not
    overwrite it."""
    item_id = 9903
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    _flow(test_db, "flow-a")
    _flow(test_db, "flow-b")

    first = handle_claim_default_deployment_flow(_request(item_id, "flow-a"))
    second = handle_claim_default_deployment_flow(_request(item_id, "flow-b"))

    assert first.result_payload["claimed"] is True
    assert second.result_payload["claimed"] is False
    assert second.result_payload["deployment_flow"] == "flow-a"


def test_refuses_a_flow_from_a_different_project(test_db: Any) -> None:
    item_id = 9904
    insert_item(test_db, id=item_id, project_sequence=item_id, workflow_id="issue")
    test_db.execute(
        "INSERT INTO projects (id,slug,name,created_at) VALUES "
        "(101,'other-project','Other','2026-09-15T00:00:00Z') "
        "ON CONFLICT (id) DO NOTHING"
    )
    test_db.commit()
    _flow(test_db, "flow-foreign", project_id=101)

    outcome = handle_claim_default_deployment_flow(_request(item_id, "flow-foreign"))

    assert outcome.primary_success is False
    assert outcome.error is not None
    assert outcome.error.code == "validation_error"
