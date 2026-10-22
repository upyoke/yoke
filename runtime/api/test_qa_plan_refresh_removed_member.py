"""Removed members refresh item plans without touching remaining shared QA."""

from contextlib import nullcontext
from unittest.mock import patch

import pytest

from runtime.api.domain.test_deployment_qa_shared_plans import (
    MEMBERS,
    RUN,
    _begin,
    _materialize,
    _seed,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers.qa_plan_materialize import handle_rematerialize
from yoke_core.domain.qa_admitted_case_reconciliation import admitted_copies_in_flight
from yoke_core.domain.qa_plan_attachments import materialize_for_item
from yoke_core.domain.qa_plan_management import replace_plan_cases
from yoke_core.domain.qa_plan_refresh_safety import refresh_invocation, refresh_recovery


def _request(**payload):
    return FunctionCallRequest(
        function="qa.plan.rematerialize",
        actor=ActorContext(actor_id="2", session_id="refresh-test"),
        target=TargetRef(kind="item", item_id=MEMBERS[0]),
        payload={"transition_id": "release", **payload},
    )


@pytest.mark.parametrize("existing", [False, True])
def test_removed_member_refresh_skips_live_shared_copies(test_db, existing):
    plan = _seed(test_db)
    source = None
    if existing:
        source = materialize_for_item(
            test_db, item_id=MEMBERS[0], transition_id="release"
        )["created_requirement_ids"][0]
    shared = _materialize(test_db, MEMBERS[0])["created_requirement_ids"][0]
    execution = _begin(test_db, MEMBERS[1])
    before = dict(
        test_db.execute(
            "SELECT * FROM qa_requirements WHERE id=%s", (shared,)
        ).fetchone()
    )
    # Removal retracts private copies; the shared group stays for the other member.
    test_db.execute(
        "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (RUN, MEMBERS[0]),
    )
    replace_plan_cases(
        test_db,
        plan_id=plan,
        cases=[
            {
                "case_key": "command-smoke",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the corrected command.",
                "expected_outcome": "the command passes",
                "method_config": {"command": "true"},
            }
        ],
    )
    test_db.commit()
    with patch(
        "yoke_core.domain.db_helpers.connect", return_value=nullcontext(test_db)
    ):
        outcome = handle_rematerialize(_request())
    assert outcome.primary_success, outcome.error
    result = outcome.result_payload["result"]
    if existing:
        assert result["refreshed_requirement_ids"] == [source]
        assert result["created_requirement_ids"] == []
    else:
        (source,) = result["created_requirement_ids"]
    assert admitted_copies_in_flight(test_db, source) == []
    assert result["corrected_admitted_copy_ids"] == []
    assert (
        test_db.execute(
            "SELECT instructions FROM qa_requirements WHERE id=%s", (source,)
        ).fetchone()[0]
        == "Run the corrected command."
    )
    assert (
        dict(
            test_db.execute(
                "SELECT * FROM qa_requirements WHERE id=%s", (shared,)
            ).fetchone()
        )
        == before
    )
    assert (
        test_db.execute(
            "SELECT state FROM qa_plan_executions WHERE id=%s", (execution["id"],)
        ).fetchone()[0]
        == "active"
    )


def test_remaining_member_still_sees_shared_copy(test_db):
    _seed(test_db)
    source = materialize_for_item(test_db, item_id=MEMBERS[1], transition_id="release")[
        "created_requirement_ids"
    ][0]
    shared = _materialize(test_db, MEMBERS[1])["created_requirement_ids"][0]
    assert [
        copy.requirement_id for copy in admitted_copies_in_flight(test_db, source)
    ] == [shared]


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


def test_removed_private_member_has_no_refresh_recipe(test_db):
    _seed(test_db)
    row = {
        "id": 0,
        "deployment_run_id": RUN,
        "deployment_stage": "item-qa",
        "deployment_member_item_id": MEMBERS[0],
    }
    assert f"--item YOK-{MEMBERS[0]} --stage item-qa" in refresh_invocation(test_db, row)
    test_db.execute(
        "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (RUN, MEMBERS[0]),
    )
    assert refresh_invocation(test_db, row) == ""
    assert "No current refresh subject" in refresh_recovery(test_db, row)


def test_shared_recipe_selects_remaining_member(test_db):
    _seed(test_db)
    shared = _materialize(test_db, MEMBERS[0])["created_requirement_ids"][0]
    row = test_db.execute(
        "SELECT * FROM qa_requirements WHERE id=%s", (shared,)
    ).fetchone()
    test_db.execute(
        "DELETE FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (RUN, MEMBERS[0]),
    )
    assert f"--item YOK-{MEMBERS[1]} --stage item-qa" in refresh_invocation(test_db, row)
    test_db.execute("DELETE FROM deployment_run_items WHERE run_id=%s", (RUN,))
    assert refresh_invocation(test_db, row) == ""
