"""Ordinary client orchestration keeps the admitted selector through begin."""

from unittest.mock import patch

import pytest

from runtime.api.domain.test_deployment_qa_admitted_plan_selection import (
    MEMBER,
    RUN,
    _seed,
)
from yoke_contracts.api.function_call import ActorContext
from yoke_core.domain import qa_plan_execution
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.qa_plan_execution_state import (
    begin_plan_execution,
    plan_execution_view,
)


def test_plan_run_materializes_then_begins_only_the_selected_frozen_plan(test_db):
    _, selected, _ = _seed(test_db)
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs["function_id"])
        payload = kwargs["payload"]
        assert payload["plan"] == str(selected)
        if kwargs["function_id"] == "qa.plan.materialize":
            receipt = materialize_deployment_qa_stage(
                test_db,
                deployment_run_id=RUN,
                deployment_stage="item-qa",
                deployment_member_item_id=MEMBER,
                agent_plan=payload["plan"],
            )
            assert receipt["created_requirement_ids"] == []
            return receipt
        assert kwargs["function_id"] == "qa.plan_execution.begin"
        execution = begin_plan_execution(
            test_db,
            deployment_run_id=RUN,
            deployment_stage="item-qa",
            deployment_member_item_id=MEMBER,
            plan=payload["plan"],
            actor_id="2",
            session_id="ordinary-selected-entrypoint",
        )
        return plan_execution_view(test_db, execution)

    def run(**kwargs):
        roster = kwargs["execution"]["requirements"]
        assert {row["plan_id"] for row in roster} == {selected}
        assert len(roster) == 2
        return {"state": "waiting", "remaining_requirement_count": 0}

    with (
        patch.object(qa_plan_execution, "_call_plan_function", side_effect=dispatch),
        patch(
            "yoke_core.domain.qa_plan_execution_run.execute_begun_plan", side_effect=run
        ),
    ):
        result = qa_plan_execution.execute_plan(
            deployment_run_id=RUN,
            deployment_stage="item-qa",
            deployment_member="member",
            plan=str(selected),
            project="yoke",
            actor=ActorContext(actor_id="2", session_id="ordinary-selected-entrypoint"),
        )
    assert result["state"] == "waiting"
    assert calls == ["qa.plan.materialize", "qa.plan_execution.begin"]


def test_private_selector_conflict_preserves_existing_cursor_and_frozen_rows(
    test_db, tmp_path, monkeypatch
):
    from runtime.api.domain.test_deployment_qa_admitted_plan_selection import _state
    from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
    from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError

    configure_test_machine(test_db, tmp_path, monkeypatch)
    from runtime.api.domain.machine_qa_host_test_support import _terminal_recipe

    held, selected, _ = _seed(
        test_db,
        cases=[
            {
                "case_key": "prepare",
                "position": 1,
                "method_id": "terminal-check",
                "instructions": "Inspect retained state",
                "expected_outcome": "Report evidence",
                "starting_state": "as_is",
                "starting_state_reason": "Preserve current machine",
                "method_config": _terminal_recipe(),
                "entry_surface": "printf done",
                "required_completion": "complete",
            },
            {
                "case_key": "receive",
                "position": 2,
                "method_id": "exploratory-mission",
                "instructions": "Inspect retained state",
                "expected_outcome": "Report evidence",
                "starting_state": "inherit",
                "method_config": {"executor": "informed_subagent"},
            },
        ],
    )
    existing = begin_plan_execution(
        test_db,
        deployment_run_id=RUN,
        deployment_stage="item-qa",
        deployment_member_item_id=MEMBER,
        plan=str(held),
        actor_id="2",
        session_id="held-owner",
    )
    before = _state(test_db)
    with pytest.raises(
        QaPlanExecutionStateError, match="qa_plan_selector_cursor_conflict"
    ) as refusal:
        begin_plan_execution(
            test_db,
            deployment_run_id=RUN,
            deployment_stage="item-qa",
            deployment_member_item_id=MEMBER,
            plan=str(selected),
            actor_id="2",
            session_id="session-agent-mission",
        )
    assert existing["id"] in str(refusal.value)
    assert _state(test_db) == before


def test_shared_selector_refuses_a_peers_previous_source_group(test_db):
    import json
    from runtime.api.domain.test_deployment_qa_shared_plans import (
        MEMBERS,
        RUN as shared_run,
        _seed,
        _materialize,
    )
    from runtime.api.domain.test_deployment_qa_admitted_plan_selection import _state
    from yoke_core.domain.qa_execution_environment_target import (
        target_digest,
        canonical_target,
    )
    from yoke_core.domain.qa_plan_management import QaPlanError

    selected = _seed(test_db)
    requirement = _materialize(test_db, MEMBERS[0])["created_requirement_ids"][0]
    raw = test_db.execute(
        "SELECT requirement_snapshot FROM deployment_run_items WHERE run_id=%s AND item_id=%s",
        (shared_run, MEMBERS[0]),
    ).fetchone()[0]
    snapshot = json.loads(raw)
    snapshot["plans"][0]["plan"]["source_revision"] = "b" * 40
    test_db.execute(
        "UPDATE deployment_run_items SET requirement_snapshot=%s WHERE run_id=%s AND item_id=%s",
        (json.dumps(snapshot), shared_run, MEMBERS[0]),
    )
    raw = test_db.execute(
        "SELECT execution_target_json FROM qa_requirements WHERE id=%s", (requirement,)
    ).fetchone()[0]
    target = json.loads(raw)
    target["deployment"]["shared_plan"]["source_revision"] = "b" * 40
    test_db.execute(
        "UPDATE qa_requirements SET execution_target_json=%s,execution_target_digest=%s WHERE id=%s",
        (canonical_target(target), target_digest(target), requirement),
    )
    test_db.commit()
    before = _state(test_db)
    with pytest.raises((QaPlanError, ValueError)):
        materialize_deployment_qa_stage(
            test_db,
            deployment_run_id=shared_run,
            deployment_stage="item-qa",
            deployment_member_item_id=MEMBERS[1],
            agent_plan=str(selected),
        )
    assert _state(test_db) == before
