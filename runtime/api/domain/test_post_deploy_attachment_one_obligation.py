"""A post-deploy attachment owes one plan group, never an item copy.

An item attaches its post-deploy plan before it lands, so the cases stay
editable while the item is in hand. Each release then runs that plan once as
a plan group for every attaching member. The item's own release transition
must never copy the plan onto the item: no run could answer that copy, so the
item would stall at close-out with nothing left to run.
"""

from __future__ import annotations

from typing import Any

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import create_smoke_plan
from yoke_core.domain.qa_plan_attachments import (
    _attached_plans,
    attach_plan_to_item,
    has_attached_plans,
    materialize_for_item,
)

RELEASE = "release"


def _member_with_attached_plan(conn: Any, *, item_id: int, slug: str) -> int:
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
    conn.commit()
    return plan_id


def test_the_release_transition_never_copies_a_post_deploy_plan(test_db) -> None:
    item_id = 9851
    plan_id = _member_with_attached_plan(test_db, item_id=item_id, slug="post-deploy")

    assert _attached_plans(test_db, item_id=item_id, transition_id=RELEASE) != {}
    assert has_attached_plans(test_db, item_id=item_id, transition_id=RELEASE) is False
    result = materialize_for_item(test_db, item_id=item_id, transition_id=RELEASE)
    assert result["created_requirement_ids"] == []
    assert result["plan_ids"] == []
    assert (
        test_db.execute(
            "SELECT id FROM qa_requirements WHERE item_id=%s AND plan_id=%s",
            (item_id, plan_id),
        ).fetchall()
        == []
    )
