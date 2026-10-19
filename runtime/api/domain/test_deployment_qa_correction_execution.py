"""Named correction walks stay on their own rows and frozen selection."""

import json

import pytest

from runtime.api.domain.test_deployment_qa_shared_plans import (
    MEMBERS,
    RUN,
    _seed,
    _materialize,
    _plan,
    _fail,
)
from runtime.api.domain.test_deployment_qa_stage_execution import _complete_case
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_requirement_correction_selection import (
    resolve_correction_selection,
)
from yoke_core.domain.qa_requirement_replacement import declare_replacements
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_plan_execution_target import build_plan_execution_target
from yoke_core.domain.deployment_qa_run_acceptance import item_qa_acceptance_blockers


@pytest.mark.parametrize("explicit_key", [True, False])
def test_named_correction_excludes_unreviewed_originals_and_other_pending_groups(
    test_db, explicit_key
):
    _seed(test_db)
    failed_id = _materialize(test_db, MEMBERS[0])["created_requirement_ids"][0]
    # An aborted original still has unanswered captured evidence, matching a
    # correction attempted before independent review settles that capture.
    original = begin_plan_execution(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBERS[0],
        actor_id="2",
        session_id="original",
    )
    finish_plan_execution(test_db, original, state="aborted", reason="correct the case")
    _fail(test_db, failed_id)
    corrected = _plan(test_db, "corrected-selected-probe")
    declaration = {"requirement_id": failed_id}
    if explicit_key:
        declaration["case_key"] = "command-smoke"
    replacements, scopes = resolve_correction_selection(test_db, [declaration])
    assert scopes
    materialized = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBERS[1],
        agent_plan=str(corrected),
        replacement_keys={"command-smoke"},
        replacement_scopes=scopes,
        replaced_requirement_ids=frozenset({failed_id}),
        commit=False,
    )
    declare_replacements(
        test_db,
        replacements,
        materialized_requirement_ids=materialized["created_requirement_ids"],
    )
    test_db.commit()
    snapshot = json.loads(
        test_db.execute(
            "SELECT requirement_snapshot FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
            (RUN, MEMBERS[1]),
        ).fetchone()[0]
    )
    assert next(p for p in snapshot["plans"] if p["plan"]["id"] == corrected)[
        "replacement_scopes"
    ]
    _materialize(test_db, MEMBERS[1])
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE deployment_run_id=%s AND plan_id=%s AND deployment_member_item_id IS NOT NULL",
            (RUN, corrected),
        ).fetchone()[0]
        == 0
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBERS[1],
        plan=str(corrected),
        actor_id="2",
        session_id="correction",
    )
    assert [case["requirement_id"] for case in execution["roster"]] == materialized[
        "created_requirement_ids"
    ]
    _complete_case(test_db, execution)
    assert all(
        not item_qa_acceptance_blockers(test_db, run_id=RUN, item_id=m) for m in MEMBERS
    )


def test_deployment_begin_payload_carries_selected_plan():
    _, payload = build_plan_execution_target(
        public_ref=None,
        transition_id=None,
        deployment_run_id="run-correction",
        deployment_stage="item-qa",
        deployment_member="EX-1",
        plan="correction",
        project="example",
    )
    assert payload["plan"] == "correction"


def test_named_plan_routes_to_its_group_instead_of_first_pending_group(test_db):
    from runtime.api.domain.test_deployment_qa_shared_plans import _attach

    _seed(test_db)
    selected = _plan(test_db, "selected-later-group")
    for member in MEMBERS:
        _attach(test_db, member, selected)
        _materialize(test_db, member)
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBERS[0],
        plan=str(selected),
        actor_id="2",
        session_id="selected-group",
    )
    assert {case["plan_id"] for case in execution["roster"]} == {selected}
    _complete_case(test_db, execution)
    # The first group remains owed; its cases did not execute as a side effect.
    assert item_qa_acceptance_blockers(test_db, run_id=RUN, item_id=MEMBERS[0])
