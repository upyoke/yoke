"""A post-deploy plan binds where post-deploy acceptance runs.

An item-scoped deployment QA stage runs the plan its member attached. That
attachment is a post-deploy binding, made at the release stage, and is a
different thing from the verification plan an optional-item-QA workflow
selects -- so it has to be allowed on its own terms.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    create_smoke_plan,
)
from yoke_core.domain.qa_plan_attachment_validation import (
    validate_item_transition,
)
from yoke_core.domain.qa_plan_management import QaPlanError


def test_a_post_deploy_plan_attaches_on_optional_item_qa(test_db) -> None:
    """The phase has to reach the binding validator, or nothing can attach.

    An optional-item-QA workflow accepts only its selected verification plan
    at a verification gate. A post-deploy attachment is a different binding,
    made at the release stage -- but the phase was dropped on the way in, so
    every attachment read as verification and the post-deploy one could not
    be made at all.
    """
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.qa_plan_attachments import attach_plan_to_item

    item_id = 9841
    insert_item(
        test_db,
        id=item_id,
        project_sequence=item_id,
        workflow_id="dash",
        status="implementing",
    )
    plan_id = create_smoke_plan(test_db, project="yoke", slug="post-deploy-plan")
    result = attach_plan_to_item(
        test_db,
        plan_id=int(plan_id),
        item_id=item_id,
        transition_id="release",
        qa_phase="post_deploy",
    )
    assert result
    attached = test_db.execute(
        "SELECT qa_phase FROM qa_plan_item_attachments WHERE item_id=%s AND plan_id=%s",
        (item_id, int(plan_id)),
    ).fetchone()
    assert str(attached["qa_phase"]) == "post_deploy"


def test_materialization_reads_the_phase_the_attachment_was_made_with(
    test_db,
) -> None:
    """Re-reading a post-deploy attachment as verification refused the release.

    The attach stores ``qa_phase``; materialization then validated the same
    binding without it, so the release transition an item could attach at
    came back as having "no reachable qa_verification gate" -- attachable,
    but never materializable, which blocked the transition itself.
    """
    from runtime.api.fixtures.backlog_inserts import insert_item
    from yoke_core.domain.qa_plan_attachments import (
        attach_plan_to_item,
        materialize_for_item,
    )
    from yoke_core.domain.qa_plan_rematerialize import rematerialize_for_item

    item_id = 9842
    insert_item(
        test_db,
        id=item_id,
        project_sequence=item_id,
        workflow_id="dash",
        status="implementing",
    )
    plan_id = create_smoke_plan(test_db, project="yoke", slug="post-deploy-release")
    attach_plan_to_item(
        test_db,
        plan_id=int(plan_id),
        item_id=item_id,
        transition_id="release",
        qa_phase="post_deploy",
    )
    # Without the phase this is exactly the refusal that blocked the release.
    with pytest.raises(QaPlanError, match="no reachable qa_verification gate"):
        validate_item_transition(
            test_db,
            item_id=item_id,
            transition_id="release",
            plan_id=int(plan_id),
        )
    materialized = materialize_for_item(
        test_db, item_id=item_id, transition_id="release"
    )
    assert materialized["created_requirement_ids"]
    # The refresh path validates the same binding and dropped the phase too.
    rematerialize_for_item(test_db, item_id=item_id, transition_id="release")
