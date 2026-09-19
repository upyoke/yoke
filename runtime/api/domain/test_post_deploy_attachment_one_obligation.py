"""One post-deploy attachment owes one obligation, not two.

An item attaches its post-deploy plan before it lands, because the cases have
to be editable while the item is still in hand. Its delivery run then admits
that plan's cases for it as a member, and those are what the run collects a
verdict for. If the item's own release transition materialized the same
attachment a second time, item-bound, that copy named an obligation only a
deployment run could answer -- and the run that would have answered it had
already finished. Nothing could discharge it, so the item stalled at its own
close-out having supplied exactly the evidence it was asked for.

These walk the real sequence: attach at release, the run admits and passes,
then the release transition.
"""

from __future__ import annotations

from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.domain.test_deployment_qa_stage_execution import _seed_run
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    create_smoke_plan,
    item_qa_stage_definitions,
    record_case_verdict,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_attachments import (
    _attached_plans,
    attach_plan_to_item,
    has_attached_plans,
    materialize_for_item,
)

ITEM_QA_STAGE = "item-qa"
RELEASE = "release"


def _member_with_attached_plan(conn: Any, *, item_id: int, slug: str) -> int:
    """An item that attached its own post-deploy plan before it landed."""
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id,
        workflow_id="dash",
        status="implementing",
    )
    plan_id = int(create_smoke_plan(conn, project="yoke", slug=slug))
    attach_plan_to_item(
        conn,
        plan_id=plan_id,
        item_id=item_id,
        transition_id=RELEASE,
        qa_phase="post_deploy",
    )
    return plan_id


def _run_admits_the_member(
    conn: Any, *, run_id: str, item_id: int, plan_id: int
) -> list[int]:
    """Stand a run on its item-scoped QA stage and admit this member's cases."""
    _seed_run(
        conn,
        run_id=run_id,
        stages=item_qa_stage_definitions(plan_id),
        members=(),
        existing_members=(item_id,),
    )
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=item_id,
    )
    return [
        int(row["id"])
        for row in conn.execute(
            "SELECT id FROM qa_requirements WHERE deployment_run_id=%s "
            "AND deployment_stage=%s AND deployment_member_item_id=%s "
            "AND method_id IS NOT NULL ORDER BY id",
            (run_id, ITEM_QA_STAGE, item_id),
        ).fetchall()
    ]


def test_a_delivered_attachment_is_not_materialized_again(test_db) -> None:
    item_id = 9851
    plan_id = _member_with_attached_plan(
        test_db, item_id=item_id, slug="delivered-post-deploy"
    )
    admitted = _run_admits_the_member(
        test_db, run_id="run-answered", item_id=item_id, plan_id=plan_id
    )
    assert admitted
    for requirement_id in admitted:
        record_case_verdict(test_db, requirement_id, "pass", evidence=True)
    test_db.commit()

    # The attachment itself is untouched: what changed is that it is no
    # longer read as owing a second obligation here.
    assert _attached_plans(
        test_db, item_id=item_id, transition_id=RELEASE
    ) != {}

    # The release transition is where the second copy used to be authored.
    assert has_attached_plans(
        test_db, item_id=item_id, transition_id=RELEASE
    ) is False
    result = materialize_for_item(
        test_db, item_id=item_id, transition_id=RELEASE
    )
    assert result["created_requirement_ids"] == []
    assert result["plan_ids"] == []
    item_bound = test_db.execute(
        "SELECT id FROM qa_requirements WHERE item_id=%s AND plan_id=%s",
        (item_id, plan_id),
    ).fetchall()
    assert item_bound == []


def test_an_undelivered_attachment_still_materializes(test_db) -> None:
    """The skip is about an answered obligation, not about being post-deploy."""
    item_id = 9852
    plan_id = _member_with_attached_plan(
        test_db, item_id=item_id, slug="undelivered-post-deploy"
    )
    test_db.commit()

    assert has_attached_plans(test_db, item_id=item_id, transition_id=RELEASE)
    result = materialize_for_item(
        test_db, item_id=item_id, transition_id=RELEASE
    )
    assert result["created_requirement_ids"]
    assert result["plan_ids"] == [plan_id]


def test_a_partly_answered_plan_still_owes_what_it_owes(test_db) -> None:
    """A plan is skipped only when every admitted case of it was answered."""
    item_id = 9853
    plan_id = _member_with_attached_plan(
        test_db, item_id=item_id, slug="partly-answered-post-deploy"
    )
    admitted = _run_admits_the_member(
        test_db, run_id="run-partial", item_id=item_id, plan_id=plan_id
    )
    assert admitted
    record_case_verdict(test_db, admitted[0], "fail", evidence=True)
    test_db.commit()

    assert has_attached_plans(test_db, item_id=item_id, transition_id=RELEASE)
    result = materialize_for_item(
        test_db, item_id=item_id, transition_id=RELEASE
    )
    assert result["created_requirement_ids"]
