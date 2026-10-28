"""Which plan refresh reaches a row, and what the refresh handler refuses."""

from contextlib import nullcontext
from unittest.mock import patch

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.qa_plan_materialize import handle_rematerialize
from yoke_core.domain.qa_plan_rematerialize import refresh_invocation, refresh_recovery

RUN = "run-refresh-recipe"
MEMBER = 4101
GROUP_TARGET = '{"deployment":{"shared_plan":{"plan_id":9,"group_id":"run-a:1"}}}'


def _request(**payload):
    return FunctionCallRequest(
        function="qa.plan.rematerialize",
        actor=ActorContext(actor_id="2", session_id="refresh-test"),
        target=TargetRef(kind="item", item_id=MEMBER),
        payload={"transition_id": "release", **payload},
    )


def _row(**values):
    row = {
        "id": 0,
        "plan_id": 9,
        "item_id": None,
        "qa_phase": "post_deploy",
        "workflow_transition_id": None,
        "deployment_run_id": RUN,
        "deployment_stage": "item-qa",
        "deployment_member_item_id": MEMBER,
        "execution_target_json": "{}",
    }
    row.update(values)
    return row


@pytest.fixture
def member_in_run():
    """Patch the membership read; the yielded list holds the run's members."""
    members = [MEMBER]
    with (
        patch(
            "yoke_core.domain.qa_plan_rematerialize.query_one",
            side_effect=lambda _conn, _sql, params: {"1": 1}
            if params[1] in members
            else None,
        ),
        patch(
            "yoke_core.domain.qa_plan_rematerialize.render_item_ref",
            side_effect=lambda _conn, item_id: f"YOK-{item_id}",
        ),
    ):
        yield members


@pytest.mark.parametrize(
    "error", [ValueError("member missing"), LookupError("plan missing")]
)
def test_lookup_refusal_teaches_subject_repair(error):
    with (
        patch("yoke_core.domain.db_helpers.connect", return_value=nullcontext(None)),
        patch(
            "yoke_core.domain.qa_plan_rematerialize.rematerialize_for_item",
            side_effect=error,
        ),
    ):
        outcome = handle_rematerialize(_request())
    assert not outcome.primary_success
    assert outcome.error.code == "qa_refresh_subject_unavailable"
    assert "correct the selected subject" in outcome.error.message


def test_item_plan_filter_is_refused_before_lookup():
    outcome = handle_rematerialize(_request(plan="smoke"))
    assert outcome.error.code == "item_plan_filter_unsupported"
    assert "Remove plan" in outcome.error.message


def test_removed_member_has_no_refresh_recipe(member_in_run):
    row = _row()
    assert refresh_invocation(None, row) == (
        f"yoke qa plan rematerialize --item YOK-{MEMBER} --stage item-qa --plan 9"
    )
    member_in_run.clear()
    assert refresh_invocation(None, row) == ""
    assert "No current refresh subject" in refresh_recovery(None, row)


def test_run_wide_row_names_the_run(member_in_run):
    row = _row(deployment_member_item_id=None, deployment_stage="run-qa")
    assert refresh_invocation(None, row) == (
        f"yoke qa plan rematerialize --deployment-run-id {RUN} --stage run-qa --plan 9"
    )


@pytest.mark.parametrize(
    "row",
    [
        _row(deployment_member_item_id=None, execution_target_json=GROUP_TARGET),
        _row(deployment_run_id=None, deployment_stage=None, item_id=MEMBER),
    ],
    ids=["plan group", "post-deploy row left on an item"],
)
def test_rows_an_edited_plan_never_reaches_have_no_refresh_recipe(row, member_in_run):
    assert refresh_invocation(None, row) == ""
    assert "plan group" in refresh_recovery(None, row)


def test_verification_item_row_names_its_transition(member_in_run):
    row = _row(
        deployment_run_id=None,
        deployment_stage=None,
        item_id=MEMBER,
        qa_phase="verification",
        workflow_transition_id="implemented",
    )
    assert refresh_invocation(None, row) == (
        f"yoke qa plan rematerialize --item YOK-{MEMBER} --transition implemented"
    )


def test_item_refresh_of_only_post_deploy_plans_refuses_by_name():
    from unittest.mock import MagicMock

    from yoke_core.domain.qa_plan_management import QaPlanError
    from yoke_core.domain.qa_plan_rematerialize import rematerialize_for_item

    with (
        patch("yoke_core.domain.qa_plan_rematerialize.lock_item_workflow_bindings"),
        patch(
            "yoke_core.domain.qa_plan_rematerialize._attached_plans",
            return_value={9: {"plan_id": 9, "qa_phase": "post_deploy"}},
        ),
        patch(
            "yoke_core.domain.qa_plan_rematerialize.render_item_ref",
            return_value=f"YOK-{MEMBER}",
        ),
        pytest.raises(QaPlanError, match="post_deploy_plan_runs_as_plan_group") as refusal,
    ):
        rematerialize_for_item(MagicMock(), item_id=MEMBER, transition_id="release")
    assert "--deployment-run-id RUN --stage item-qa --plan P" in str(refusal.value)


def test_run_wide_refresh_at_an_item_stage_refuses_plan_groups(test_db):
    from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
        ITEM_QA_STAGE,
        seed_member_qa_case,
    )
    from yoke_core.domain.qa_plan_management import QaPlanError
    from yoke_core.domain.qa_plan_rematerialize_deployment import (
        rematerialize_for_deployment_stage,
    )

    seed_member_qa_case(test_db, run_id=RUN, member_item_id=MEMBER)
    with pytest.raises(QaPlanError, match="plan_group_not_rematerialized") as refusal:
        rematerialize_for_deployment_stage(
            test_db, deployment_run_id=RUN, deployment_stage=ITEM_QA_STAGE
        )
    assert "an edited plan runs on the next release" in str(refusal.value)
