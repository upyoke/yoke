"""An item-scoped QA stage either can do its job or is refused before deploying.

Item QA proves each member against the requirement snapshot the composition
freeze writes, and only a flow that takes delivery custody freezes one, so a
member on a custody-free flow is refused. A memberless run is judged by what
it owes: a stage run whose candidates were targeted out passes its item QA
with a named "no member owes this target" result, while a run that is the
completion flow for delivery-ready items no other release holds, yet
enrolled none, is refused at validation and again before execution.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain import deployment_runs_validation as validation
from yoke_core.domain.deployment_run_item_qa_membership import (
    NO_MEMBER_OWES_TARGET,
    item_qa_membership_verdict,
    memberless_item_qa_refusal,
    owed_delivery_item_ids,
)
from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item
from yoke_core.domain.handlers.deployment_run_execution import (
    handle_deployment_execution_context,
)

ITEM_QA_STAGE = {
    "name": "item-qa",
    "step_runner": "qa",
    "stage_kind": "qa",
    "scope": "item",
    "target": {
        "kind": "persistent_environment",
        "environment": "stage",
        "source_stage": "deploy",
    },
    "verdict": {"mode": "agent_only"},
}
DEPLOY_STAGE = {
    "name": "deploy",
    "step_runner": "auto",
    "stage_kind": "execution",
    "scope": "run",
}
PRODUCTION_FLOW = "item-qa-production"
STAGE_FLOW = "item-qa-stage"
ITEM_ID = 9441


def _flow(conn: Any, flow: str, *, custody: int, item_qa: bool = True) -> None:
    stages = [DEPLOY_STAGE, ITEM_QA_STAGE] if item_qa else [DEPLOY_STAGE]
    conn.execute(
        "INSERT INTO deployment_flows(id,project_id,name,description,stages,"
        "created_at,status,definition_schema_version,takes_delivery_custody) "
        "VALUES (%s,1,%s,'',%s,%s,'active',2,%s)",
        (flow, flow, json.dumps(stages), "2026-10-06T00:00:00Z", custody),
    )


def _run(conn: Any, flow: str, *, run_id: str = "", status: str = "created") -> str:
    run_id = run_id or f"run-{flow}"
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "created_at) VALUES (%s,1,%s,%s,%s,%s)",
        (run_id, flow, "a" * 40, status, "2026-10-06T00:00:00Z"),
    )
    conn.commit()
    return run_id


def _release_ready_item(conn: Any, flow: str) -> None:
    """A landed Dash at its release wait, closed by *flow*."""
    insert_item(
        conn,
        id=ITEM_ID,
        project_sequence=ITEM_ID - 9000,
        workflow_id="dash",
        status="release",
        deployment_flow=flow,
    )
    conn.commit()


def test_member_on_a_custody_free_item_qa_flow_is_refused(test_db: Any) -> None:
    _flow(test_db, STAGE_FLOW, custody=0)
    run_id = _run(test_db, STAGE_FLOW)
    _release_ready_item(test_db, STAGE_FLOW)
    for require_members in (True, False):
        refusal, notice = item_qa_membership_verdict(
            test_db, run_id, require_members=require_members
        )
        assert refusal.startswith("item_qa_flow_without_delivery_custody:")
        assert "yoke deployment-flows list --project" in refusal
        assert notice == ""
    with pytest.raises(ValueError, match="item_qa_flow_without_delivery_custody"):
        cmd_add_item(run_id, ITEM_ID)
    count = test_db.execute(
        "SELECT COUNT(*) FROM deployment_run_items WHERE run_id=%s", (run_id,)
    ).fetchone()[0]
    assert count == 0


def test_run_owing_delivery_without_members_is_refused_except_at_create(
    test_db: Any,
) -> None:
    _flow(test_db, PRODUCTION_FLOW, custody=1)
    run_id = _run(test_db, PRODUCTION_FLOW)
    _release_ready_item(test_db, PRODUCTION_FLOW)
    refusal, notice = item_qa_membership_verdict(test_db, run_id)
    assert refusal.startswith("item_qa_run_without_members:")
    assert f"'{PRODUCTION_FLOW}'" in refusal
    assert f"yoke deployment-runs add-item {run_id} PREFIX-N" in refusal
    assert "listed below" not in refusal
    assert notice == ""
    # Creation mints an itemless run so add-item can attach to it.
    assert item_qa_membership_verdict(test_db, run_id, require_members=False) == (
        "",
        "",
    )


@pytest.mark.parametrize("custody", [0, 1])
def test_stage_run_whose_candidates_were_targeted_out_passes_with_a_named_result(
    test_db: Any, custody: int
) -> None:
    _flow(test_db, PRODUCTION_FLOW, custody=1)
    _flow(test_db, STAGE_FLOW, custody=custody)
    run_id = _run(test_db, STAGE_FLOW)
    _release_ready_item(test_db, PRODUCTION_FLOW)
    refusal, notice = item_qa_membership_verdict(test_db, run_id)
    assert refusal == ""
    assert NO_MEMBER_OWES_TARGET in notice
    assert notice.startswith("item-qa:")


@pytest.mark.parametrize(
    ("state", "owed"),
    [("held", False), ("remerged", True), ("unheld", True), ("undetermined", True)],
)
def test_only_a_landing_another_release_holds_is_not_owed(
    test_db: Any, monkeypatch: pytest.MonkeyPatch, state: str, owed: bool
) -> None:
    """Re-merged and unreadable landings stay owed, so the check fails closed."""
    from yoke_core.domain import delivery_landing_custody

    _flow(test_db, PRODUCTION_FLOW, custody=1)
    run_id = _run(test_db, PRODUCTION_FLOW)
    _release_ready_item(test_db, PRODUCTION_FLOW)
    seen: dict[str, Any] = {}

    def custody(_conn, *, project_id, item_ids, exclude_run_id=""):
        seen["exclude_run_id"] = exclude_run_id
        return {
            item_id: delivery_landing_custody.LandingCustody(
                item_id=item_id, landing_sha="b" * 40, state=state
            )
            for item_id in item_ids
        }

    monkeypatch.setattr(delivery_landing_custody, "landing_custody", custody)
    assert owed_delivery_item_ids(test_db, run_id) == ((ITEM_ID,) if owed else ())
    assert seen["exclude_run_id"] == run_id
    refusal, notice = item_qa_membership_verdict(test_db, run_id)
    assert refusal.startswith("item_qa_run_without_members:") is owed
    assert (NO_MEMBER_OWES_TARGET in notice) is not owed


def test_members_or_removals_satisfy_a_custody_run(test_db: Any) -> None:
    _flow(test_db, PRODUCTION_FLOW, custody=1)
    run_id = _run(test_db, PRODUCTION_FLOW)
    _release_ready_item(test_db, PRODUCTION_FLOW)
    cmd_add_item(run_id, ITEM_ID)
    assert item_qa_membership_verdict(test_db, run_id) == ("", "")
    test_db.execute("DELETE FROM deployment_run_items WHERE run_id=%s", (run_id,))
    test_db.execute(
        "UPDATE deployment_runs SET membership_removals=%s WHERE id=%s",
        (json.dumps([{"item_id": ITEM_ID, "reason": "red QA"}]), run_id),
    )
    test_db.commit()
    assert item_qa_membership_verdict(test_db, run_id) == ("", "")


@pytest.mark.parametrize("custody", [0, 1])
def test_flow_without_item_qa_is_never_judged(test_db: Any, custody: int) -> None:
    _flow(test_db, PRODUCTION_FLOW, custody=custody, item_qa=False)
    run_id = _run(test_db, PRODUCTION_FLOW)
    _release_ready_item(test_db, PRODUCTION_FLOW)
    assert item_qa_membership_verdict(test_db, run_id) == ("", "")


def _isolate_candidate_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold every candidate walk still so only the item-QA verdict varies."""
    for name, value in (
        ("record_bound_sources", lambda *_a, **_k: None),
        ("resolve_candidate_custody", lambda *_a, **_k: None),
        ("carried_enrollment_blocked", lambda *_a, **_k: "test-fixture"),
        ("enroll_carried_members", lambda *_a, **_k: ()),
        ("carried_project_ids", lambda *_a, **_k: (1,)),
        ("carried_membership_refusal", lambda *_a, **_k: ""),
        ("unclosable_final_member_refusal", lambda *_a, **_k: ""),
        ("unadmitted_post_deploy_notice", lambda *_a, **_k: ""),
        ("inert_membership_notice", lambda *_a, **_k: ""),
        ("skipped_candidate_notice", lambda *_a, **_k: ""),
    ):
        monkeypatch.setattr(validation, name, value)


def test_validate_and_pre_start_refuse_a_run_owing_delivery_without_members(
    test_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_candidate_reads(monkeypatch)
    _flow(test_db, PRODUCTION_FLOW, custody=1)
    run_id = _run(test_db, PRODUCTION_FLOW)
    _release_ready_item(test_db, PRODUCTION_FLOW)
    valid, message = validation.cmd_validate_composition(run_id)
    assert not valid
    assert "item_qa_run_without_members" in message

    monkeypatch.setattr(
        "yoke_core.domain.handlers.deployment_run_execution.require_run_driver",
        lambda _request, _run_id: None,
    )
    monkeypatch.setattr(
        "yoke_core.domain.handlers.deployment_run_execution._record_bound_sources",
        lambda _run_id: {},
    )
    outcome = handle_deployment_execution_context(
        deployment_request(
            function="deployment_runs.execution.context",
            target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        )
    )
    assert not outcome.primary_success
    assert outcome.error is not None
    assert outcome.error.code == "composition_invalid"
    assert "item_qa_run_without_members" in outcome.error.message


def test_an_unreadable_completion_flow_fails_closed(
    test_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A delivery-ready item whose project default cannot be read is not dropped."""
    from yoke_core.domain import workflow_project_defaults

    _flow(test_db, PRODUCTION_FLOW, custody=1)
    run_id = _run(test_db, PRODUCTION_FLOW)
    _release_ready_item(test_db, "")
    test_db.execute("UPDATE items SET deployment_flow=NULL WHERE id=%s", (ITEM_ID,))
    test_db.commit()

    def unreadable(*_args, **_kwargs):
        raise workflow_project_defaults.WorkflowProjectDefaultError("unreadable")

    monkeypatch.setattr(workflow_project_defaults, "get_delivery_default", unreadable)
    refusal, notice = item_qa_membership_verdict(test_db, run_id)
    assert refusal.startswith("item_qa_owed_delivery_unreadable:")
    assert "cannot be read" in refusal
    assert notice == ""
    assert memberless_item_qa_refusal(test_db, run_id).startswith(
        "item_qa_owed_delivery_unreadable:"
    )
    assert item_qa_membership_verdict(test_db, run_id, require_members=False) == (
        "",
        "",
    )
