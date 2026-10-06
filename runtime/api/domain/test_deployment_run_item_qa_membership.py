"""A run whose item-scoped QA stage could never pass is refused before it deploys.

Item QA proves each member against the requirement snapshot the composition
freeze writes, and only a flow that takes delivery custody freezes one. A
custody-free flow with such a stage, or a run that reaches start with no
member, used to validate clean and then fail at item QA after the whole
deploy had run. Both are now named refusals at composition, while a custody
run's ordinary itemless create-then-attach path is unchanged.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import deployment_runs_validation as validation
from yoke_core.domain.deployment_run_item_qa_membership import (
    item_qa_membership_refusal,
)
from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item

ITEM_QA_STAGES = [
    {
        "name": "deploy",
        "step_runner": "auto",
        "stage_kind": "execution",
        "scope": "run",
    },
    {
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
    },
]
RUN_ONLY_STAGES = ITEM_QA_STAGES[:1]
ITEM_ID = 9441


def _flow_and_run(
    conn: Any, *, flow: str, custody: int, stages: list[dict[str, Any]]
) -> str:
    conn.execute(
        "INSERT INTO deployment_flows(id,project_id,name,description,stages,"
        "created_at,status,definition_schema_version,takes_delivery_custody) "
        "VALUES (%s,1,%s,'',%s,%s,'active',2,%s)",
        (flow, flow, json.dumps(stages), "2026-10-06T00:00:00Z", custody),
    )
    run_id = f"run-{flow}"
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "created_at) VALUES (%s,1,%s,%s,'created',%s)",
        (run_id, flow, "a" * 40, "2026-10-06T00:00:00Z"),
    )
    insert_item(
        conn,
        id=ITEM_ID,
        project_sequence=ITEM_ID - 9000,
        workflow_id="blitz",
        status="implementing",
        deployment_flow=flow,
    )
    conn.commit()
    return run_id


def test_custody_free_item_qa_flow_is_refused_with_recovery(test_db: Any) -> None:
    run_id = _flow_and_run(
        test_db, flow="no-custody-item-qa", custody=0, stages=ITEM_QA_STAGES
    )
    for require_members in (True, False):
        refusal = item_qa_membership_refusal(
            test_db, run_id, require_members=require_members
        )
        assert refusal.startswith("item_qa_flow_without_delivery_custody:")
        assert "item-qa" in refusal
        assert "takes_delivery_custody" in refusal
        assert "yoke deployment-flows list --project" in refusal


def test_add_item_refuses_a_member_no_snapshot_can_prove(test_db: Any) -> None:
    run_id = _flow_and_run(
        test_db, flow="no-custody-item-qa", custody=0, stages=ITEM_QA_STAGES
    )
    with pytest.raises(ValueError, match="item_qa_flow_without_delivery_custody"):
        cmd_add_item(run_id, ITEM_ID)
    count = test_db.execute(
        "SELECT COUNT(*) FROM deployment_run_items WHERE run_id=%s", (run_id,)
    ).fetchone()[0]
    assert count == 0


def test_custody_run_without_members_is_refused_only_before_start(
    test_db: Any,
) -> None:
    run_id = _flow_and_run(
        test_db, flow="custody-item-qa", custody=1, stages=ITEM_QA_STAGES
    )
    refusal = item_qa_membership_refusal(test_db, run_id)
    assert refusal.startswith("item_qa_run_without_members:")
    assert "yoke deployment-runs add-item" in refusal
    # Creation mints an itemless run so add-item can attach to it.
    assert item_qa_membership_refusal(test_db, run_id, require_members=False) == ""


def test_custody_run_with_a_member_or_removal_passes(test_db: Any) -> None:
    run_id = _flow_and_run(
        test_db, flow="custody-item-qa", custody=1, stages=ITEM_QA_STAGES
    )
    cmd_add_item(run_id, ITEM_ID)
    assert item_qa_membership_refusal(test_db, run_id) == ""
    test_db.execute("DELETE FROM deployment_run_items WHERE run_id=%s", (run_id,))
    test_db.execute(
        "UPDATE deployment_runs SET membership_removals=%s WHERE id=%s",
        (json.dumps([{"item_id": ITEM_ID, "reason": "red QA"}]), run_id),
    )
    test_db.commit()
    assert item_qa_membership_refusal(test_db, run_id) == ""


@pytest.mark.parametrize("custody", [0, 1])
def test_flow_without_item_qa_is_never_refused(test_db: Any, custody: int) -> None:
    run_id = _flow_and_run(
        test_db, flow=f"run-only-{custody}", custody=custody, stages=RUN_ONLY_STAGES
    )
    assert item_qa_membership_refusal(test_db, run_id) == ""


def _isolate_candidate_reads(monkeypatch: pytest.MonkeyPatch) -> None:
    """Hold every candidate walk still so only the composition verdict varies."""
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


def test_validate_composition_refuses_a_memberless_item_qa_run(
    test_db: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    _isolate_candidate_reads(monkeypatch)
    run_id = _flow_and_run(
        test_db, flow="custody-item-qa", custody=1, stages=ITEM_QA_STAGES
    )
    valid, message = validation.cmd_validate_composition(run_id)
    assert not valid
    assert "item_qa_run_without_members" in message
    valid, message = validation.cmd_validate_composition(
        run_id, require_item_qa_members=False
    )
    assert valid, message
