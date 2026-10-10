"""A stage run whose candidate was targeted out passes item QA; production does not.

One landed Dash owes post-deploy QA on stage and on prod, through a stage run
and a production run of separate flows. Waiving the stage obligation targets
the item out of the stage run for real, so that run is left memberless; the
production run's flow is the item's completion flow, so the same item
leaves it owing a delivery when it has no member. Pre-start, dispatch, the
outstanding report, and the prior-stage gate all answer both runs alike.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.domain.handlers.deployment_handler_test_support import (
    deployment_request,
)
from runtime.api.domain.test_deployment_run_item_qa_membership import (
    _isolate_candidate_reads,
)
from runtime.api.domain.test_release_member_target_enrollment import _pair
from runtime.api.fixtures.carried_release_candidate import record_landing_receipt
from yoke_contracts.api.function_call import TargetRef
from yoke_core.domain import deployment_runs_validation as validation
from yoke_core.domain.deployment_qa_stage_dispatch import (
    materialize_and_gate_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_outstanding import qa_stage_outstanding
from yoke_core.domain.deployment_qa_stage_prerequisites import prior_stage_refusals
from yoke_core.domain.delivery_landing_custody import HELD, landing_custody
from yoke_core.domain.deployment_run_item_qa_membership import (
    NO_MEMBER_OWES_TARGET,
    owed_delivery_item_ids,
)
from yoke_core.domain.deployment_run_member_targeting import run_needs_member
from yoke_core.domain.handlers.deployment_run_execution import (
    handle_deployment_execution_context,
)

ITEM_ID = 9691
LATER_QA_STAGE = {
    "name": "run-visual-qa",
    "step_runner": "qa",
    "stage_kind": "qa",
    "scope": "run",
}


def _memberless(conn: Any, run_id: str) -> list[dict[str, Any]]:
    """Drop *run_id*'s membership and return its flow's stages."""
    conn.execute("DELETE FROM deployment_run_items WHERE run_id=%s", (run_id,))
    conn.execute(
        "UPDATE deployment_runs SET status='created',current_stage=NULL WHERE id=%s",
        (run_id,),
    )
    conn.commit()
    row = conn.execute(
        "SELECT df.stages FROM deployment_runs dr JOIN deployment_flows df "
        "ON df.id=dr.flow WHERE dr.id=%s",
        (run_id,),
    ).fetchone()
    return json.loads(row[0])


@pytest.fixture()
def targeted_out(test_db: Any) -> Any:
    sources = _pair(test_db, item_id=ITEM_ID)
    test_db.execute(
        "UPDATE qa_requirements SET waived_at=%s WHERE id=%s",
        ("2026-10-06T00:00:00Z", sources["stage"]),
    )
    test_db.execute(
        "UPDATE items SET deployment_flow='flow-run-prod' WHERE id=%s", (ITEM_ID,)
    )
    test_db.commit()
    assert not run_needs_member(test_db, run_id="run-stage", item_id=ITEM_ID)
    return test_db


def _pre_start(monkeypatch: pytest.MonkeyPatch, run_id: str):
    _isolate_candidate_reads(monkeypatch)
    for name, value in (
        ("require_run_driver", lambda _request, _run_id: None),
        ("_record_bound_sources", lambda _run_id: {}),
    ):
        monkeypatch.setattr(
            f"yoke_core.domain.handlers.deployment_run_execution.{name}", value
        )
    return handle_deployment_execution_context(
        deployment_request(
            function="deployment_runs.execution.context",
            target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        )
    )


def test_targeted_out_stage_run_starts_and_passes_every_item_qa_check(
    targeted_out: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    conn = targeted_out
    stages = _memberless(conn, "run-stage")

    valid, message = validation.cmd_validate_composition("run-stage")
    assert valid, message
    assert NO_MEMBER_OWES_TARGET in message
    outcome = _pre_start(monkeypatch, "run-stage")
    assert outcome.primary_success, outcome.error

    conn.execute(
        "UPDATE deployment_runs SET status='executing',current_stage='member-qa' "
        "WHERE id='run-stage'"
    )
    conn.commit()
    item_qa = next(stage for stage in stages if stage.get("scope") == "item")
    assert materialize_and_gate_deployment_qa_stage(
        conn, item_qa, run_id="run-stage"
    ) == (0, NO_MEMBER_OWES_TARGET)
    outstanding = qa_stage_outstanding(conn, run_id="run-stage", stage_name="member-qa")
    assert outstanding is not None
    assert (outstanding.waiting, outstanding.lines) == (0, ())
    assert outstanding.no_obligation_lines == (NO_MEMBER_OWES_TARGET,)
    later = [*stages, LATER_QA_STAGE]
    assert (
        prior_stage_refusals(
            conn, run_id="run-stage", stages=later, start_stage="run-visual-qa"
        )
        == []
    )


def test_memberless_production_run_fails_closed_everywhere(
    targeted_out: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stage run's membership is supplemental, so it holds nothing here."""
    conn = targeted_out
    stages = _memberless(conn, "run-prod")

    valid, message = validation.cmd_validate_composition("run-prod")
    assert not valid
    assert "item_qa_run_without_members" in message
    outcome = _pre_start(monkeypatch, "run-prod")
    assert outcome.error is not None
    assert outcome.error.code == "composition_invalid"
    assert "item_qa_run_without_members" in outcome.error.message

    item_qa = next(stage for stage in stages if stage.get("scope") == "item")
    code, refusal = materialize_and_gate_deployment_qa_stage(
        conn, item_qa, run_id="run-prod"
    )
    assert code == 1
    assert refusal.startswith("item_qa_run_without_members:")
    outstanding = qa_stage_outstanding(conn, run_id="run-prod", stage_name="member-qa")
    assert outstanding is not None
    assert outstanding.waiting == 1
    assert outstanding.lines[0].startswith("item_qa_run_without_members:")
    refusals = prior_stage_refusals(
        conn,
        run_id="run-prod",
        stages=[*stages, LATER_QA_STAGE],
        start_stage="run-visual-qa",
    )
    assert len(refusals) == 1
    assert "item_qa_run_without_members" in refusals[0]


def test_a_supplemental_holder_carrying_the_landing_still_leaves_it_owed(
    targeted_out: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The stage run carries the landing, yet holds nothing for prod."""
    from yoke_core.domain import delivery_landing_custody
    from yoke_core.domain.deployment_run_candidate_containment import (
        CONTAINED,
        ContainmentVerdict,
    )

    monkeypatch.setattr(
        delivery_landing_custody,
        "candidate_contains_commit",
        lambda *_args, **_kwargs: ContainmentVerdict(CONTAINED),
    )
    conn = targeted_out
    _memberless(conn, "run-prod")
    lineage = conn.execute(
        "SELECT release_lineage FROM deployment_runs WHERE id='run-stage'"
    ).fetchone()[0]
    record_landing_receipt(conn, ITEM_ID, branch="landed-item", tip=lineage)

    anyone = landing_custody(conn, project_id=1, item_ids=[ITEM_ID])
    assert anyone[ITEM_ID].state == HELD
    assert anyone[ITEM_ID].run_id == "run-stage"
    for_prod = landing_custody(
        conn, project_id=1, item_ids=[ITEM_ID], exclude_run_id="run-prod"
    )
    assert for_prod[ITEM_ID].state != HELD
    assert owed_delivery_item_ids(conn, "run-prod") == (ITEM_ID,)
