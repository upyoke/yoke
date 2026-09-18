"""An item whose flow asks it to prove itself must bring its own plan.

Both halves matter: the flow has to actually declare an item-scoped QA
stage, and only then is a missing plan worth refusing a landing over. A
flow with no such stage — which is most flows, in most projects — is
untouched.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    create_smoke_plan,
    item_qa_stage_definitions,
)
from yoke_core.domain.deployment_flow_versioning import cmd_create
from yoke_core.domain.qa_item_stage_plan_gate import (
    flow_has_item_scoped_qa_stage,
    missing_item_qa_plan_refusal,
)

ITEM_ID = 9831


def _flow(conn: Any, flow_id: str, stages: list[dict]) -> str:
    cmd_create(
        conn, flow_id, "yoke", flow_id, "", json.dumps(stages), status="disabled"
    )
    conn.commit()
    return flow_id


def _run_scoped_stages() -> list[dict]:
    """A flow whose only QA stage answers for the whole run, not per item."""
    stages = item_qa_stage_definitions(None, environment="development")
    stages[1]["scope"] = "run"
    return stages


def _refusal(conn: Any, flow_id: str) -> str:
    return missing_item_qa_plan_refusal(
        conn,
        item_id=ITEM_ID,
        public_ref="YOK-1927",
        project="yoke",
        flow_id=flow_id,
    )


def test_item_scoped_qa_stage_is_recognised(test_db) -> None:
    item_flow = _flow(
        test_db,
        "flow-item-scoped",
        item_qa_stage_definitions(None, environment="development"),
    )
    run_flow = _flow(test_db, "flow-run-scoped", _run_scoped_stages())
    assert flow_has_item_scoped_qa_stage(test_db, item_flow) is True
    assert flow_has_item_scoped_qa_stage(test_db, run_flow) is False
    assert flow_has_item_scoped_qa_stage(test_db, "") is False
    assert flow_has_item_scoped_qa_stage(test_db, "flow-that-does-not-exist") is False


def test_landing_is_refused_without_an_attached_plan(test_db) -> None:
    flow_id = _flow(
        test_db,
        "flow-refuses",
        item_qa_stage_definitions(None, environment="development"),
    )
    refusal = _refusal(test_db, flow_id)
    assert refusal
    # The refusal has to be actionable on its own: what is wrong, and the
    # attach-then-dry-run recipe that fixes it.
    assert "item-scoped QA stage" in refusal
    assert "yoke qa item-plan attach --item YOK-1927" in refusal
    assert "--qa-phase post_deploy" in refusal
    assert "yoke qa plan run --item YOK-1927" in refusal


def test_an_attached_post_deploy_plan_clears_the_landing(test_db) -> None:
    flow_id = _flow(
        test_db,
        "flow-cleared",
        item_qa_stage_definitions(None, environment="development"),
    )
    plan_id = create_smoke_plan(test_db, project="yoke", slug="member-owned-plan")
    test_db.execute(
        "INSERT INTO qa_plan_item_attachments"
        "(item_id,plan_id,transition_id,qa_phase,attached_at)"
        " VALUES (%s,%s,%s,'post_deploy',%s)",
        (ITEM_ID, int(plan_id), "reviewing-implementation", "2026-09-18T00:00:00Z"),
    )
    test_db.commit()
    assert _refusal(test_db, flow_id) == ""


def test_a_flow_without_an_item_scoped_stage_never_asks(test_db) -> None:
    flow_id = _flow(test_db, "flow-unaffected", _run_scoped_stages())
    assert _refusal(test_db, flow_id) == ""


def test_an_item_with_no_flow_is_unaffected(test_db) -> None:
    assert _refusal(test_db, "") == ""
