"""A succeeded run's scoped QA verdicts still gate the item's release.

The pipeline refuses to advance past an unaccepted QA stage, so these
cases cover what happens *after* the run finished: a rejection recorded
later, a stage whose acceptance was never settled at all, and the batch
member whose own QA is still outstanding while a sibling's has passed.
"""

from __future__ import annotations

import json
from typing import Any

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_qa_stage_ordering import (
    _stages as _ordered_stages,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.deployment_flow_versioning import cmd_create
from yoke_core.domain.deployment_qa_run_acceptance import (
    item_qa_acceptance_blockers,
)
from yoke_core.domain.deployment_qa_stage_contract import (
    DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution


def _settle(conn: Any, *, run_id: str, stage: str, member: int | None) -> None:
    """Drive one stage subject all the way to a recorded acceptance."""
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage=stage,
        deployment_member_item_id=member,
    )
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage=stage,
        deployment_member_item_id=member,
        actor_id="2",
        session_id=f"{stage}-{member}",
    )
    _complete_case(conn, execution)
    assert deployment_qa_stage_status(
        conn, run_id=run_id, stage_name=stage, member_item_id=member
    )["accepted"]


def _finish_run(conn: Any, run_id: str) -> None:
    """The pipeline's own terminal state, after every stage was walked."""
    conn.execute(
        "UPDATE deployment_runs SET status='succeeded',current_stage='complete' "
        "WHERE id=%s",
        (run_id,),
    )
    conn.commit()


def _acceptance_requirement_id(conn: Any, run_id: str, stage: str) -> int:
    row = conn.execute(
        "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
        "AND deployment_stage=%s AND qa_kind=%s ORDER BY id DESC LIMIT 1",
        (run_id, stage, DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND),
    ).fetchone()
    assert row is not None
    return int(row["id"])


def test_unsettled_stage_blocks_a_run_that_already_succeeded(test_db) -> None:
    plan_id = _plan(test_db, "unsettled-smoke")
    _seed_run(
        test_db,
        run_id="run-unsettled",
        stages=_stages(plan_id),
        members=(9810,),
    )
    _finish_run(test_db, "run-unsettled")

    blockers = item_qa_acceptance_blockers(
        test_db, run_id="run-unsettled", item_id=9810
    )
    assert blockers, "a stage that never settled must not read as accepted"
    assert any("item-qa" in reason for reason in blockers)


def test_settled_stage_clears_the_item(test_db) -> None:
    plan_id = _plan(test_db, "settled-smoke")
    _seed_run(
        test_db,
        run_id="run-settled",
        stages=_stages(plan_id),
        members=(9811,),
    )
    _settle(test_db, run_id="run-settled", stage="item-qa", member=9811)
    _finish_run(test_db, "run-settled")

    assert item_qa_acceptance_blockers(
        test_db, run_id="run-settled", item_id=9811
    ) == []


def test_rejection_recorded_after_the_run_finished_blocks(test_db) -> None:
    """The gate the pipeline passed can still be revoked by a human verdict."""
    plan_id = _plan(test_db, "revoked-smoke")
    _seed_run(
        test_db,
        run_id="run-revoked",
        stages=_stages(plan_id),
        members=(9812,),
    )
    _settle(test_db, run_id="run-revoked", stage="item-qa", member=9812)
    _finish_run(test_db, "run-revoked")
    assert item_qa_acceptance_blockers(
        test_db, run_id="run-revoked", item_id=9812
    ) == []

    requirement_id = _acceptance_requirement_id(test_db, "run-revoked", "item-qa")
    # Later than the acceptance the pipeline recorded: newest verdict wins,
    # which is the same rule the active-stage gate reads.
    now = iso8601_now()
    test_db.execute(
        "INSERT INTO qa_runs("
        "qa_requirement_id,performed_by,qa_kind,verdict,verdict_reason,"
        "raw_result,started_at,completed_at,created_at"
        ") VALUES (%s,'human_review',%s,'fail','rejected on the deployed target',"
        "%s,%s,%s,%s)",
        (
            requirement_id,
            DEPLOYMENT_STAGE_ACCEPTANCE_QA_KIND,
            json.dumps({"note": "regression on the stage target"}),
            now,
            now,
            now,
        ),
    )
    test_db.commit()

    blockers = item_qa_acceptance_blockers(
        test_db, run_id="run-revoked", item_id=9812
    )
    assert any("was rejected" in reason for reason in blockers)


def test_each_member_answers_only_for_its_own_item_scoped_stage(test_db) -> None:
    plan_id = _plan(test_db, "per-member-smoke")
    _seed_run(
        test_db,
        run_id="run-members",
        stages=_stages(plan_id),
        members=(9813, 9814),
    )
    _settle(test_db, run_id="run-members", stage="item-qa", member=9813)
    _finish_run(test_db, "run-members")

    assert item_qa_acceptance_blockers(
        test_db, run_id="run-members", item_id=9813
    ) == []
    assert item_qa_acceptance_blockers(
        test_db, run_id="run-members", item_id=9814
    )


def test_run_scoped_stage_blocks_every_member_until_it_settles(test_db) -> None:
    plan_id = _plan(test_db, "shared-release-smoke")
    _seed_run(
        test_db,
        run_id="run-shared",
        stages=_ordered_stages(plan_id),
        members=(9815,),
    )
    for stage in ("member-qa-one", "member-qa-two"):
        test_db.execute(
            "UPDATE deployment_runs SET current_stage=%s WHERE id=%s",
            (stage, "run-shared"),
        )
        test_db.commit()
        _settle(test_db, run_id="run-shared", stage=stage, member=9815)
    _finish_run(test_db, "run-shared")

    blockers = item_qa_acceptance_blockers(
        test_db, run_id="run-shared", item_id=9815
    )
    assert any("release-qa" in reason for reason in blockers)
    assert not any("member-qa" in reason for reason in blockers)


def test_legacy_flow_owes_no_scoped_verdicts(test_db) -> None:
    """A schema-1 definition has no scoped stages; the legacy table rules."""
    stages = [{"name": "deploy-stage", "step_runner": "auto"}]
    cmd_create(
        test_db,
        "flow-legacy-acceptance",
        "yoke",
        "flow-legacy-acceptance",
        "",
        json.dumps(stages),
        status="disabled",
    )
    insert_item(
        test_db, id=9816, project_sequence=9816, workflow_id="issue", status="release"
    )
    test_db.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "current_stage,created_at) VALUES "
        "('run-legacy',1,'flow-legacy-acceptance',%s,'succeeded','complete',%s)",
        ("a" * 40, "2026-09-14T00:00:00Z"),
    )
    test_db.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) "
        "VALUES ('run-legacy',9816,%s)",
        ("2026-09-14T00:00:00Z",),
    )
    test_db.commit()

    assert item_qa_acceptance_blockers(
        test_db, run_id="run-legacy", item_id=9816
    ) == []
