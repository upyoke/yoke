"""Explicit selectors reuse frozen admissions and leave other plans alone."""

import json

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_management import QaPlanError, replace_plan_cases

RUN = "run-admitted-selection"
MEMBER = 9755


def _state(conn):
    return {
        table: [
            tuple(row)
            for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1").fetchall()
        ]
        for table in (
            "qa_requirements",
            "deployment_runs",
            "deployment_run_items",
            "qa_plan_executions",
        )
    }


def _seed(conn):
    held = _plan(conn, "held-failed-plan")
    selected = _plan(conn, "selected-frozen-plan")
    replace_plan_cases(
        conn,
        plan_id=selected,
        cases=[
            {
                "case_key": key,
                "position": position,
                "method_id": "command",
                "instructions": "frozen command",
                "expected_outcome": "passes",
                "method_config": {"command": "true"},
            }
            for position, key in enumerate(("prepare", "receive"), 1)
        ],
    )
    _seed_run(conn, run_id=RUN, stages=_stages(held), members=(MEMBER,))
    from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot

    row = conn.execute(
        "SELECT requirement_snapshot FROM deployment_run_items WHERE run_id=%s", (RUN,)
    ).fetchone()
    snapshot = json.loads(row[0])
    snapshot["plans"] = [
        {
            **_plan_snapshot(conn, selected, project_id=1),
            "attachment": {"qa_phase": "post_deploy", "transition_id": ""},
        }
    ]
    conn.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=%s WHERE run_id=%s",
        (json.dumps(snapshot), RUN),
    )
    conn.commit()
    receipt = materialize_deployment_qa_stage(
        conn,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
    )
    return held, selected, receipt


@pytest.mark.parametrize("by_slug", [False, True])
def test_selects_frozen_admission_without_writers_or_other_plan(test_db, by_slug):
    held, selected, _ = _seed(test_db)
    test_db.execute(
        "UPDATE qa_plan_cases SET instructions='changed live body' WHERE plan_id=%s",
        (selected,),
    )
    test_db.commit()
    before = _state(test_db)
    selector = "selected-frozen-plan" if by_slug else str(selected)
    result = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
        agent_plan=selector,
    )
    assert result["created_requirement_ids"] == []
    assert len(result["existing_requirement_ids"]) == 2
    assert _state(test_db) == before
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
        plan=selector,
        actor_id="2",
        session_id="selected-plan-session",
    )
    assert {row["requirement_id"] for row in execution["roster"]} == set(
        result["existing_requirement_ids"]
    )
    assert [row["instructions"] for row in execution["roster"]] == [
        "frozen command"
    ] * 2
    assert held != selected


@pytest.mark.parametrize(
    "mutation", ["withdraw", "missing", "target", "unknown", "unadmitted"]
)
def test_invalid_selection_preserves_all_admission_and_execution_rows(
    test_db, mutation
):
    _, selected, _ = _seed(test_db)
    selector = str(selected)
    if mutation == "unknown":
        selector = "no-such-plan"
    elif mutation == "unadmitted":
        selector = str(_plan(test_db, "unadmitted-plan"))
    else:
        row_id = test_db.execute(
            "SELECT id FROM qa_requirements WHERE plan_id=%s ORDER BY id LIMIT 1",
            (selected,),
        ).fetchone()[0]
        if mutation == "withdraw":
            test_db.execute(
                "UPDATE qa_requirements SET retracted_at=NOW() WHERE id=%s", (row_id,)
            )
        elif mutation == "missing":
            test_db.execute("DELETE FROM qa_requirements WHERE id=%s", (row_id,))
        else:
            test_db.execute(
                "UPDATE qa_requirements SET execution_target_digest='wrong' WHERE id=%s",
                (row_id,),
            )
        test_db.commit()
    before = _state(test_db)
    with pytest.raises(QaPlanError):
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=RUN,
            deployment_stage="item-qa",
            deployment_member_item_id=MEMBER,
            agent_plan=selector,
        )
    assert _state(test_db) == before


def test_shared_member_selects_only_its_attached_group(test_db):
    from runtime.api.domain.test_deployment_qa_shared_plans import (
        MEMBERS,
        RUN as shared_run,
        _seed,
        _materialize,
        _attach,
    )

    selected = _seed(test_db)
    _materialize(test_db, MEMBERS[0])
    before = _state(test_db)
    receipt = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=shared_run,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBERS[1],
        agent_plan=str(selected),
    )
    assert (
        receipt["existing_requirement_ids"] and receipt["created_requirement_ids"] == []
    )
    assert _state(test_db) == before
    foreign = _plan(test_db, "other-members-plan")
    _attach(test_db, MEMBERS[0], foreign)
    _materialize(test_db, MEMBERS[0])
    before = _state(test_db)
    with pytest.raises(QaPlanError):
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=shared_run,
            deployment_stage="item-qa",
            deployment_member_item_id=MEMBERS[1],
            agent_plan=str(foreign),
        )
    assert _state(test_db) == before


def test_selected_as_is_inherit_chain_keeps_held_failed_plan_owed(
    test_db, tmp_path, monkeypatch
):
    from runtime.api.domain.machine_qa_host_test_support import (
        configure_test_machine,
        _terminal_recipe,
    )
    from runtime.api.domain.test_deployment_qa_shared_plans import _fail
    from yoke_core.domain.deployment_requirement_snapshots import _plan_snapshot
    from yoke_core.domain.qa_plan_execution_store import select_plan_execution

    configure_test_machine(test_db, tmp_path, monkeypatch)
    held, selected, _ = _seed(test_db)
    held_walk = begin_plan_execution(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
        plan=str(held),
        actor_id="2",
        session_id="other-held-session",
    )
    _fail(test_db, held_walk["roster"][0]["requirement_id"])
    # Prepare the chain before its first admission; no host action runs here.
    second_run = "run-inherited-selection"
    replace_plan_cases(
        test_db,
        plan_id=selected,
        cases=[
            {
                "case_key": key,
                "position": position,
                "method_id": "terminal-check"
                if key == "prepare"
                else "exploratory-mission",
                "instructions": "Inspect the retained state",
                "expected_outcome": "Report evidence",
                "starting_state": state,
                "starting_state_reason": "Preserve current machine state"
                if state == "as_is"
                else None,
                "method_config": _terminal_recipe()
                if key == "prepare"
                else {"executor": "informed_subagent"},
                "entry_surface": "printf done" if key == "prepare" else None,
                "required_completion": "complete" if key == "prepare" else None,
                "host_baselines": [],
            }
            for position, (key, state) in enumerate(
                (("prepare", "as_is"), ("receive", "inherit")), 1
            )
        ],
    )
    _seed_run(test_db, run_id=second_run, stages=_stages(held), members=(9756, 9757))
    row = test_db.execute(
        "SELECT requirement_snapshot FROM deployment_run_items WHERE run_id=%s",
        (second_run,),
    ).fetchone()
    frozen = json.loads(row[0])
    frozen["plans"] = [
        {
            **_plan_snapshot(test_db, selected, project_id=1),
            "attachment": {"qa_phase": "post_deploy", "transition_id": ""},
        }
    ]
    test_db.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=%s WHERE run_id=%s",
        (json.dumps(frozen), second_run),
    )
    from runtime.api.domain.test_deployment_qa_shared_plans import _attach

    for member in (9756, 9757):
        _attach(test_db, member, held)
        _attach(test_db, member, selected)
    test_db.commit()
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=second_run,
        deployment_stage="item-qa",
        deployment_member_item_id=9756,
    )
    other = begin_plan_execution(
        test_db,
        deployment_run_id=second_run,
        deployment_stage="item-qa",
        deployment_member_item_id=9756,
        plan=str(held),
        actor_id="2",
        session_id="held-failed-session",
    )
    _fail(test_db, other["roster"][0]["requirement_id"])
    before = _state(test_db)
    receipt = materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=second_run,
        deployment_stage="item-qa",
        deployment_member_item_id=9756,
        agent_plan=str(selected),
    )
    assert _state(test_db) == before
    walk = begin_plan_execution(
        test_db,
        deployment_run_id=second_run,
        deployment_stage="item-qa",
        deployment_member_item_id=9756,
        plan=str(selected),
        actor_id="2",
        session_id="session-agent-mission",
    )
    assert [r["starting_state"] for r in walk["roster"]] == ["as_is", "inherit"]
    assert [r["requirement_id"] for r in walk["roster"]] == receipt[
        "existing_requirement_ids"
    ]
    assert select_plan_execution(test_db, other["id"], lock=False)["state"] == "active"
