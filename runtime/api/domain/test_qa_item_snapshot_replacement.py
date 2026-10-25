"""Item corrections explicitly refresh stable snapshots before replacement."""

import pytest

from runtime.api.domain.test_qa_plan_case_currency import _case, _materialized
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_core.domain.handlers.qa_plan_materialize import (
    handle_materialize, handle_rematerialize,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_plan_attachments import attach_plan_to_item, materialize_for_item
from yoke_core.domain.qa_plan_execution_roster import ordered_plan_requirements
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases

ITEM = 8620
TRANSITION = "implemented"


def _request(*, item_id=ITEM, replacements=()):
    return FunctionCallRequest(
        function="qa.plan.materialize",
        actor=ActorContext(actor_id="op", session_id="snapshot-correction"),
        target=TargetRef(kind="item", item_id=item_id),
        payload={"transition_id": TRANSITION, "replacements": list(replacements)},
    )


def _declare(failed, key="corrected", *, item_id=ITEM):
    return handle_materialize(_request(
        item_id=item_id, replacements=[{"case_key": key, "requirement_id": failed}],
    ))


def _refresh():
    request = _request()
    request.function = "qa.plan.rematerialize"
    request.payload = {"transition_id": TRANSITION}
    return handle_rematerialize(request)


def _rows(conn):
    return [dict(row) for row in conn.execute(
        "SELECT * FROM qa_requirements WHERE item_id=%s ORDER BY id", (ITEM,),
    ).fetchall()]


def _history(conn, requirement):
    return [dict(row) for row in conn.execute(
        "SELECT * FROM qa_runs WHERE qa_requirement_id=%s ORDER BY id", (requirement,),
    ).fetchall()]


def _correct(conn, plan, **overrides):
    replace_plan_cases(conn, plan_id=plan, cases=[
        _case(), _case(case_key="corrected", position=2, **overrides),
    ])


def test_refresh_then_declare_preserves_failure_and_moves_grading(test_db):
    plan, failed = _materialized(test_db, item_id=ITEM)
    record_case_verdict(test_db, failed, "fail", evidence=True)
    history = _history(test_db, failed)
    before = _rows(test_db)
    _correct(test_db, plan)

    for _ in range(2):
        result = handle_materialize(_request())
        assert result.primary_success
        assert result.result_payload["result"]["created_requirement_ids"] == []
        assert _rows(test_db) == before
    refused = _declare(failed)
    assert not refused.primary_success
    assert refused.error.code == "replacement_refused"
    message = refused.error.message
    assert "replacement_materialization_stale:" in message
    subject = f"--item {render_item_ref(test_db, ITEM)} --transition {TRANSITION} --project yoke"
    assert f"yoke qa plan rematerialize {subject}" in message
    assert f"yoke qa plan materialize {subject} --replaces corrected={failed}" in message
    assert _rows(test_db) == before

    refreshed = _refresh()
    assert refreshed.primary_success
    successor = refreshed.result_payload["result"]["created_requirement_ids"][0]
    declared = _declare(failed)
    assert declared.primary_success
    assert declared.result_payload["result"]["replacements"] == [{
        "requirement_id": failed, "replacement_requirement_id": successor,
    }]
    assert [row["requirement_id"] for row in ordered_plan_requirements(
        test_db, item_id=ITEM, transition_id=TRANSITION,
    )] == [successor]
    assert _history(test_db, failed) == history
    record_case_verdict(test_db, successor, "pass", evidence=True)
    assert _rows(test_db)[0]["superseded_by_requirement_id"] == successor
    assert _history(test_db, failed) == history
    assert _history(test_db, successor)[0]["verdict"] == "pass"
    for _ in range(2):
        assert handle_materialize(_request()).result_payload["result"]["created_requirement_ids"] == []
    assert len(_rows(test_db)) == 2


@pytest.mark.parametrize("key", ["misspelled", "command"])
def test_unknown_key_and_same_case_do_not_recommend_refresh(test_db, key):
    plan, failed = _materialized(test_db, item_id=ITEM)
    _correct(test_db, plan)
    result = _declare(failed, key)
    code = "replacement_case_unknown" if key == "misspelled" else "replacement_case_corrected_in_place"
    assert code in result.error.message
    assert "yoke qa plan rematerialize" not in result.error.message
    assert len(_rows(test_db)) == 1


def test_failed_case_from_another_item_is_not_a_stale_snapshot(test_db):
    plan, failed = _materialized(test_db, item_id=ITEM)
    _materialized(test_db, item_id=ITEM + 1)
    _correct(test_db, plan)
    result = _declare(failed, item_id=ITEM + 1)
    assert "replacement_scope_mismatch:" in result.error.message
    assert "yoke qa plan rematerialize" not in result.error.message


def test_key_in_an_unattached_plan_is_unknown_for_this_item(test_db):
    _, failed = _materialized(test_db, item_id=ITEM)
    extra = create_plan(test_db, project="yoke", slug="unattached", name="Unattached")
    _correct(test_db, extra["id"])
    result = _declare(failed)
    assert "replacement_case_unknown:" in result.error.message
    assert "yoke qa plan rematerialize" not in result.error.message


def test_ambiguous_current_key_is_not_a_stale_snapshot(test_db):
    plan, failed = _materialized(test_db, item_id=ITEM)
    extra = create_plan(test_db, project="yoke", slug="another", name="Another plan")
    replace_plan_cases(test_db, plan_id=extra["id"], cases=[_case(case_key="other")])
    attach_plan_to_item(test_db, plan_id=extra["id"], item_id=ITEM, transition_id=TRANSITION)
    materialize_for_item(test_db, item_id=ITEM, transition_id=TRANSITION)
    _correct(test_db, plan)
    _correct(test_db, extra["id"])
    result = _declare(failed)
    assert "replacement_case_ambiguous:" in result.error.message
    assert "yoke qa plan rematerialize" not in result.error.message


def test_adding_a_case_to_a_live_walk_refuses_and_rolls_back(test_db):
    plan, _ = _materialized(test_db, item_id=ITEM)
    execution = begin_plan_execution(
        test_db, item_id=ITEM, transition_id=TRANSITION,
        actor_id="op", session_id="snapshot-correction",
    )
    before = _rows(test_db)
    _correct(test_db, plan)
    result = _refresh()
    assert not result.primary_success
    assert "plan_execution_in_flight:" in result.error.message
    assert f"yoke qa plan abort --execution-id {execution['id']} --reason" in result.error.message
    assert _rows(test_db) == before


def test_refused_declaration_rolls_back_a_newly_attached_plan_snapshot(test_db):
    _, failed = _materialized(test_db, item_id=ITEM)
    extra = create_plan(test_db, project="yoke", slug="extra", name="Extra plan")
    replace_plan_cases(test_db, plan_id=extra["id"], cases=[_case(case_key="new")])
    attach_plan_to_item(test_db, plan_id=extra["id"], item_id=ITEM, transition_id=TRANSITION)
    before = _rows(test_db)
    result = _declare(failed, "unknown")
    assert not result.primary_success
    assert _rows(test_db) == before
