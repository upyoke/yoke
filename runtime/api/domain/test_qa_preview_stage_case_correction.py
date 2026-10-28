"""A failed admitted case is correctable on a run-preview stage.

An admitted copy labels its row with the environment its stage froze. A plan
case materialized on the same stage has to carry the same label, or the
corrected case reads as a different scope and supersession refuses it as
``replacement_link_scope_changed``. Persistent stages always carried it; these
pin the run-preview stage to the same rule.
"""

from __future__ import annotations

from typing import Any

from runtime.api.domain.test_deployment_qa_multi_item_scoped_stages import (
    LINEAGE,
    PREVIEW_QA,
    _bind_plan,
    _environment_id,
    _point_run_at_environment,
    _preview_qa_stages,
    _seed_ephemeral_capability,
)
from runtime.api.fixtures.deployment_admitted_case_fixture import intake_requirement
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    record_case_verdict,
    seed_run_standing_on_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_member_requirements,
)
from yoke_core.domain.qa_requirement_supersession import supersede_requirement
from yoke_core.domain.qa_requirement_waive_liveness import (
    NOT_LIVE_CODE,
    RequirementNotLiveError,
    require_live_for_waiver,
)

import pytest


def _preview_stage_rows(conn: Any, *, item_id: int, run_id: str) -> tuple[int, int]:
    """Materialize the preview stage; return its admitted copy and plan case."""
    intake_id = intake_requirement(conn, item_id=item_id)
    _seed_ephemeral_capability(conn)
    seed_run_standing_on_qa_stage(
        conn,
        run_id=run_id,
        project="yoke",
        stages=_preview_qa_stages(),
        members=(item_id,),
        lineage=LINEAGE,
        receipt_target_kind="run_preview",
    )
    conn.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=%s "
        "WHERE run_id=%s AND item_id=%s",
        (
            snapshot_member_requirements(
                conn,
                run_id=run_id,
                item_id=item_id,
                selection_json=requirement_selection(requirement_ids=(intake_id,)),
            ),
            run_id,
            item_id,
        ),
    )
    environment_id = _environment_id(conn)
    _point_run_at_environment(conn, run_id, environment_id)
    plan_id = _bind_plan(conn, slug=f"{run_id}-plan", environment_id=environment_id)
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage=PREVIEW_QA,
        deployment_member_item_id=item_id,
    )
    # Post-deploy plans run as plan groups; a member's correction of its own
    # admitted case selects the plan for exactly the corrected case key.
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage=PREVIEW_QA,
        deployment_member_item_id=item_id,
        agent_plan=str(plan_id),
        replacement_keys={"command-smoke"},
    )
    rows = conn.execute(
        "SELECT id, plan_id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage=%s ORDER BY id",
        (run_id, PREVIEW_QA),
    ).fetchall()
    admitted = [int(row["id"]) for row in rows if row["plan_id"] is None]
    planned = [int(row["id"]) for row in rows if row["plan_id"] is not None]
    assert len(admitted) == 1 and planned, rows
    return admitted[0], planned[0]


def _target_env(conn: Any, requirement_id: int) -> Any:
    return conn.execute(
        "SELECT target_env FROM qa_requirements WHERE id=%s", (requirement_id,)
    ).fetchone()["target_env"]


def test_plan_case_on_preview_stage_supersedes_the_failed_admitted_case(
    test_db,
) -> None:
    run_id = "run-preview-correction"
    admitted_id, corrected_id = _preview_stage_rows(
        test_db, item_id=9861, run_id=run_id
    )
    assert _target_env(test_db, corrected_id) == _target_env(test_db, admitted_id)
    assert _target_env(test_db, corrected_id)
    record_case_verdict(test_db, admitted_id, "fail", evidence=False)
    record_case_verdict(test_db, corrected_id, "pass", evidence=True)

    receipt = supersede_requirement(
        test_db,
        requirement_id=admitted_id,
        superseded_by_requirement_id=corrected_id,
        rationale="the admitted case asserted a route the preview does not serve",
        source="operator",
    )

    assert receipt["superseded_by_requirement_id"] == corrected_id
    with pytest.raises(RequirementNotLiveError) as refusal:
        require_live_for_waiver(test_db, admitted_id)
    assert NOT_LIVE_CODE in str(refusal.value)
    assert f"--requirement-id {corrected_id}" in str(refusal.value)
