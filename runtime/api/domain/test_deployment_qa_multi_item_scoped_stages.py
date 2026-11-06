"""A flow can run item-scoped QA at more than one stage.

Two bugs lived in the gap this file covers: a discharged member left zero
acceptance rows, so the next item-scoped stage refused them; and a plan
bound to a persistent environment was skipped at a run_preview stage
because the preview target has no environment id.
"""

from __future__ import annotations

from runtime.api.domain.deployment_qa_multi_item_scoped_stages_test_support import (
    LINEAGE as LINEAGE,
    PREVIEW_QA as PREVIEW_QA,
    _bind_plan as _bind_plan,
    _environment_id as _environment_id,
    _item_qa as _item_qa,
    _point_run_at_environment as _point_run_at_environment,
    _preview_producer as _preview_producer,
    _preview_qa_stages as _preview_qa_stages,
    _seed_ephemeral_capability as _seed_ephemeral_capability,
)


from typing import Any

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    seed_run_standing_on_qa_stage,
)
from yoke_core.domain.deployment_qa_plan_group_writes import ensure_groups
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_qa_stage_prerequisites import (
    prior_stage_refusals,
    require_prior_stage_acceptance,
)
from yoke_core.domain.post_deploy_verification_answer import NO_OBLIGATION_QA_KIND

PROD_QA = "prod-item-qa"


def _deploy(name: str) -> dict[str, Any]:
    return {
        "name": name,
        "step_runner": "auto",
        "stage_kind": "execution",
        "scope": "run",
    }


def _two_item_qa_stages() -> list[dict[str, Any]]:
    return [
        _deploy("preview-deploy"),
        _item_qa(
            PREVIEW_QA, source_stage="preview-deploy", kind="persistent_environment"
        ),
        _deploy("prod-deploy"),
        _item_qa(PROD_QA, source_stage="prod-deploy", kind="persistent_environment"),
    ]


def _ensure_environment(conn: Any, name: str, url: str) -> int:
    conn.execute(
        "INSERT INTO environments(site,project_id,name,url,settings,created_at) "
        "SELECT id,1,%s,%s,'{}',%s FROM sites WHERE project_id=1 ORDER BY id "
        "LIMIT 1 ON CONFLICT(project_id,name) DO UPDATE SET url=EXCLUDED.url",
        (name, url, "2026-09-21T00:00:00Z"),
    )
    conn.commit()
    return _environment_id(conn, name)


def _no_obligation(conn: Any, item_id: int) -> None:
    conn.execute(
        "INSERT INTO qa_requirements(item_id,qa_kind,qa_phase,blocking_mode,"
        "requirement_source,instructions,workflow_transition_id,created_at) "
        "VALUES (%s,%s,'post_deploy','non_blocking','explicit',%s,'release',"
        "'2026-09-21T00:00:00Z')",
        (int(item_id), NO_OBLIGATION_QA_KIND, "nothing observable once deployed"),
    )
    conn.commit()


def _attach_plan(conn: Any, *, item_id: int, plan_id: int) -> None:
    conn.execute(
        "INSERT INTO qa_plan_item_attachments"
        "(item_id,plan_id,transition_id,qa_phase,attached_at)"
        " VALUES (%s,%s,'release','post_deploy',%s)",
        (int(item_id), int(plan_id), "2026-09-21T00:00:00Z"),
    )
    conn.commit()


def test_discharged_member_does_not_block_the_next_item_scoped_stage(test_db) -> None:
    item_id = 9851
    run_id = "run-multi-qa-discharged"
    stages = _two_item_qa_stages()
    seed_run_standing_on_qa_stage(
        test_db,
        run_id=run_id,
        project="yoke",
        stages=stages,
        members=(item_id,),
        lineage=LINEAGE,
    )
    _no_obligation(test_db, item_id)

    assert (
        prior_stage_refusals(test_db, run_id=run_id, stages=stages, start_stage=PROD_QA)
        == []
    )
    require_prior_stage_acceptance(
        test_db, run_id=run_id, stages=stages, start_stage=PROD_QA
    )


def test_unasked_member_still_blocks_the_next_item_scoped_stage(test_db) -> None:
    item_id = 9852
    run_id = "run-multi-qa-unasked"
    stages = _two_item_qa_stages()
    seed_run_standing_on_qa_stage(
        test_db,
        run_id=run_id,
        project="yoke",
        stages=stages,
        members=(item_id,),
        lineage=LINEAGE,
    )

    refusals = prior_stage_refusals(
        test_db, run_id=run_id, stages=stages, start_stage=PROD_QA
    )
    assert len(refusals) == 1
    assert "0 current acceptance records" in refusals[0]
    with pytest.raises(ValueError, match="prior scoped QA acceptance"):
        require_prior_stage_acceptance(
            test_db, run_id=run_id, stages=stages, start_stage=PROD_QA
        )


def test_environment_bound_plan_runs_at_preview_standing_in_for_that_environment(
    test_db,
) -> None:
    item_id = 9853
    run_id = "run-preview-bound-plan"
    _seed_ephemeral_capability(test_db)
    seed_run_standing_on_qa_stage(
        test_db,
        run_id=run_id,
        project="yoke",
        stages=_preview_qa_stages(),
        members=(item_id,),
        lineage=LINEAGE,
        receipt_target_kind="run_preview",
    )
    environment_id = _environment_id(test_db)
    _point_run_at_environment(test_db, run_id, environment_id)
    plan_id = _bind_plan(
        test_db, slug="preview-bound-stage", environment_id=environment_id
    )
    _attach_plan(test_db, item_id=item_id, plan_id=plan_id)

    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=PREVIEW_QA,
        deployment_member_item_id=item_id,
    )
    created = result["created_requirement_ids"]
    assert created
    assert {
        row[0]
        for row in test_db.execute(
            "SELECT plan_id FROM qa_requirements WHERE id=ANY(%s)", (created,)
        ).fetchall()
    } == {plan_id}
    assert run_groups(test_db, [run_id], PREVIEW_QA) == []


def test_environment_bound_plan_skips_preview_standing_in_for_a_different_environment(
    test_db,
) -> None:
    item_id = 9854
    run_id = "run-preview-wrong-env"
    _seed_ephemeral_capability(test_db)
    seed_run_standing_on_qa_stage(
        test_db,
        run_id=run_id,
        project="yoke",
        stages=_preview_qa_stages(),
        members=(item_id,),
        lineage=LINEAGE,
        receipt_target_kind="run_preview",
    )
    stage_id = _environment_id(test_db, "stage")
    prod_id = _ensure_environment(test_db, "prod", "https://prod.example.test")
    _point_run_at_environment(test_db, run_id, stage_id)
    plan_id = _bind_plan(test_db, slug="preview-bound-prod", environment_id=prod_id)
    _attach_plan(test_db, item_id=item_id, plan_id=plan_id)

    assert ensure_groups(test_db, run_id, PREVIEW_QA) == []
    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=PREVIEW_QA,
        deployment_member_item_id=item_id,
    )
    assert result["created_requirement_ids"] == []
    from yoke_core.domain.post_deploy_verification_answer import (
        member_post_deploy_answer,
        NOT_REQUIRED,
    )

    assert (
        member_post_deploy_answer(
            test_db, {"id": run_id, "member_item_id": item_id}
        ).verdict
        == NOT_REQUIRED
    )
