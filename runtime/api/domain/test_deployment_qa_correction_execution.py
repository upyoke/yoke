"""Named correction walks stay on their own rows and their own plan group."""

import pytest

from runtime.api.domain.test_deployment_qa_plan_groups import (
    MEMBERS,
    RUN,
    SLUG,
    _attach,
    _seed,
)
from runtime.api.domain.test_deployment_qa_shared_plans import _fail
from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
)
from yoke_core.domain.deployment_qa_plan_group_dispatch import settle_group
from yoke_core.domain.deployment_qa_plan_group_writes import (
    ensure_groups,
    group_subject,
)
from yoke_core.domain.deployment_qa_plan_groups import run_groups
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    finish_plan_execution,
)
from yoke_core.domain.qa_plan_execution_target import build_plan_execution_target
from yoke_core.domain.qa_plan_management import replace_plan_cases
from yoke_core.domain.qa_requirement_correction_selection import (
    resolve_correction_selection,
)
from yoke_core.domain.qa_requirement_replacement import declare_replacements

STAGE = "item-qa"
OTHER = "other-pending-plan"


def _begin(conn, plan, session):
    return begin_plan_execution(
        conn,
        deployment_run_id=RUN,
        deployment_stage=STAGE,
        deployment_member_item_id=None,
        plan=plan,
        actor_id="2",
        session_id=session,
    )


def _groups(conn):
    return {group.plan_id: group for group in run_groups(conn, [RUN], STAGE)}


def _two_groups(conn):
    """Every member attaches both plans, so the run holds two open groups."""
    smoke = _seed(conn)
    other = _plan(conn, OTHER)
    for member in MEMBERS:
        _attach(conn, member, other)
    ensure_groups(conn, RUN, STAGE)
    conn.commit()
    return smoke, other


@pytest.mark.parametrize("explicit_key", [True, False])
def test_named_correction_excludes_unreviewed_originals_and_other_pending_groups(
    test_db, explicit_key
):
    smoke, other = _two_groups(test_db)
    # An aborted original still has unanswered captured evidence, matching a
    # correction attempted before independent review settles that capture.
    original = _begin(test_db, SLUG, "original")
    failed_id = int(original["roster"][0]["requirement_id"])
    finish_plan_execution(test_db, original, state="aborted", reason="correct the case")
    _fail(test_db, failed_id)
    replace_plan_cases(
        test_db,
        plan_id=smoke,
        cases=[
            {
                "case_key": "command-smoke",
                "position": 1,
                "method_id": "command",
                "instructions": "Run the corrected group probe.",
                "expected_outcome": "The corrected probe passes.",
                "method_config": {"command": "echo corrected"},
            }
        ],
    )
    declaration = {"requirement_id": failed_id}
    if explicit_key:
        declaration["case_key"] = "command-smoke"
    replacements, scopes = resolve_correction_selection(test_db, [declaration])
    assert scopes
    materialized = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=RUN,
        deployment_stage=STAGE,
        agent_plan=SLUG,
        replacement_keys={"command-smoke"},
        replacement_scopes=scopes,
        replaced_requirement_ids=frozenset({failed_id}),
        commit=False,
    )
    corrected = materialized["created_requirement_ids"]
    assert corrected
    declare_replacements(test_db, replacements, materialized_requirement_ids=corrected)
    test_db.commit()

    execution = _begin(test_db, SLUG, "correction")
    assert [case["requirement_id"] for case in execution["roster"]] == corrected
    _complete_case(test_db, execution)
    groups = _groups(test_db)
    group = groups[smoke]
    if not group.closed:
        settle_group(test_db, group_subject(test_db, RUN, STAGE, group, require_active=False))
        group = _groups(test_db)[smoke]
    assert group.covered_item_ids == MEMBERS
    # The other plan's group stays owed; its cases did not execute.
    assert _groups(test_db)[other].open


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
    smoke, other = _two_groups(test_db)

    execution = _begin(test_db, OTHER, "selected-group")

    assert {case["plan_id"] for case in execution["roster"]} == {other}
    _complete_case(test_db, execution)
    # The first group remains owed; its cases did not execute as a side effect.
    assert _groups(test_db)[smoke].open
