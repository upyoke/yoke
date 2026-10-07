"""Manual project plans own fresh snapshots without item or delivery gates."""

import pytest

from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_requirement_snapshot_convergence import (
    assert_requirement_execution_snapshot_invariants,
)
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    finish_plan_execution,
    lock_plan_execution,
)
from yoke_core.domain.qa_plan_execution_store import QaPlanExecutionStateError
from yoke_core.domain.qa_case_execution_context import get_case_execution_context
from yoke_core.domain.qa_standalone_execution import begin_standalone_execution
from yoke_core.domain.qa_standalone_schema import assert_standalone_subjects
from yoke_core.domain.qa_plan_detail import get_plan
from yoke_core.domain.qa_artifact_owner import requirement_storage_owner
from yoke_core.domain.qa_artifacts import case_artifact_subject

SHA = "a" * 40


def _plan(conn):
    plan = create_plan(conn, project="yoke", slug="manual-proof", name="Manual proof")
    replace_plan_cases(
        conn,
        plan_id=plan["id"],
        cases=[
            {
                "case_key": key,
                "position": position,
                "method_id": "command",
                "instructions": "Run the command",
                "expected_outcome": "It passes",
                "method_config": {"command": "true"},
            }
            for key, position in (("later", 2), ("first", 1))
        ],
    )
    conn.commit()
    return plan


def _begin(conn, **kwargs):
    return begin_standalone_execution(
        conn,
        plan="manual-proof",
        project="yoke",
        actor_id="7",
        session_id="manual-owner",
        source_revision=SHA,
        checkout_path="/tmp/manual-proof",
        **kwargs,
    )


def test_fresh_manual_runs_keep_order_and_never_acquire_gate_subjects():
    with test_database() as conn:
        _plan(conn)
        assert_standalone_subjects(conn)
        execution = _begin(conn)
        assert [case["case_key"] for case in execution["roster"]] == ["first", "later"]
        for case in execution["roster"]:
            assert case["item_id"] is None and case["deployment_run_id"] is None
            assert case["workflow_transition_id"] is None
            assert case["standalone_execution_id"] == execution["id"]
            assert (
                get_case_execution_context(conn, requirement_id=case["requirement_id"])[
                    "standalone_source_revision"
                ]
                == SHA
            )
        finish_plan_execution(conn, execution, state="aborted", reason="manual-abort")
        fresh = _begin(conn)
        owner = requirement_storage_owner(conn, fresh["roster"][0]["requirement_id"])
        assert owner["project"] == "yoke"
        assert case_artifact_subject(owner) == f"standalone-{fresh['id']}"
        proof = get_plan(conn, plan_id=fresh["standalone_plan_id"])["cases"][0][
            "proofs"
        ][0]
        assert proof["standalone_execution_id"] == fresh["id"]
        assert fresh["id"] != execution["id"]
        assert_requirement_execution_snapshot_invariants(conn)
        assert {case["requirement_id"] for case in fresh["roster"]}.isdisjoint(
            case["requirement_id"] for case in execution["roster"]
        )
        assert (
            conn.execute("SELECT COUNT(*) FROM qa_plan_item_attachments").fetchone()[0]
            == 0
        )


def test_same_second_abort_then_restart_resumes_the_new_live_owner(monkeypatch):
    from yoke_core.domain import qa_standalone_execution as standalone
    from yoke_core.domain.qa_plan_execution_continuation import latest_plan_execution

    identifiers = iter(("f" * 32, "1" * 32, "2" * 32))
    monkeypatch.setattr(standalone, "uuid4", lambda: next(identifiers))
    monkeypatch.setattr(standalone, "iso8601_now", lambda: "2026-09-30T12:00:00Z")
    with test_database() as conn:
        _plan(conn)
        old = _begin(conn)
        finish_plan_execution(conn, old, state="aborted", reason="first")
        current = _begin(conn)
        resumed = _begin(conn)
        assert resumed["id"] == current["id"]
        finish_plan_execution(conn, current, state="aborted", reason="second")
        latest = latest_plan_execution(
            conn, standalone_plan_id=current["standalone_plan_id"]
        )
        assert latest["id"] == current["id"]


def test_manual_resume_keeps_snapshot_cursor_and_source_binding():
    with test_database() as conn:
        _plan(conn)
        execution = _begin(conn)
        case = execution["roster"][0]
        advance_plan_execution(
            conn,
            execution,
            ordinal=0,
            requirement_id=case["requirement_id"],
            result={
                "requirement_id": case["requirement_id"],
                "runner_id": "worktree_run",
                "verdict": "pass",
                "case_outcome": "passed",
            },
        )
        resumed = _begin(conn)
        assert resumed["id"] == execution["id"]
        assert resumed["cursor_ordinal"] == 1
        with pytest.raises(
            QaPlanExecutionStateError, match="standalone_source_changed"
        ):
            begin_standalone_execution(
                conn,
                plan="manual-proof",
                project="yoke",
                actor_id="7",
                session_id="manual-owner",
                source_revision="b" * 40,
            )
        conn.rollback()
        assert (
            lock_plan_execution(conn, execution["id"])["roster_digest"]
            == resumed["roster_digest"]
        )


def test_bad_source_refuses_before_materialization_commits():
    with test_database() as conn:
        _plan(conn)
        with pytest.raises(
            QaPlanExecutionStateError, match="standalone_commit_required"
        ):
            begin_standalone_execution(
                conn,
                plan="manual-proof",
                project="yoke",
                actor_id="7",
                session_id="manual-owner",
            )
        conn.rollback()
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM qa_requirements WHERE standalone_execution_id IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM qa_plan_executions WHERE standalone_plan_id IS NOT NULL"
            ).fetchone()[0]
            == 0
        )


def _machine_chain(conn, plan_id):
    """A fresh-host case and the case that continues on the machine it leaves."""
    replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[
            {
                "case_key": key,
                "method_id": "terminal-check",
                "instructions": "Check the terminal",
                "expected_outcome": "Done",
                "entry_surface": "/usr/bin/true",
                "required_completion": "done",
                **start,
                "method_config": {"steps": [{"key": "done", "expect": "done"}]},
            }
            for key, start in (
                ("first", {"host_baselines": ["fresh-host"]}),
                ("second", {"starting_state": "inherit"}),
            )
        ],
    )


def _plan_case_request(execution, ordinal, function="test_machine.plan_case.begin"):
    from yoke_contracts.api.function_call import (
        ActorContext,
        FunctionCallRequest,
        TargetRef,
    )

    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="2", session_id="session-machine-plan"),
        target=TargetRef(kind="global", project_id="yoke"),
        payload={
            "execution_id": execution["id"],
            "ordinal": ordinal,
            "requirement_id": execution["roster"][ordinal]["requirement_id"],
        },
    )


def test_inheriting_case_names_only_its_own_standalone_predecessor(
    test_db, tmp_path, monkeypatch
):
    from runtime.api.domain.machine_qa_host_test_support import (
        configure_test_machine,
    )
    from yoke_core.domain.handlers.machine_qa_plan_case import handle_plan_case_begin

    configure_test_machine(test_db, tmp_path, monkeypatch)
    plan = _plan(test_db)
    _machine_chain(test_db, plan["id"])
    old = _begin(test_db)
    finish_plan_execution(test_db, old, state="aborted", reason="new-run")
    current = _begin(test_db)
    assert [case["starting_state"] for case in current["roster"]] == [
        "baseline",
        "inherit",
    ]
    # The predecessor never ran in this execution, so the follower is
    # recorded blocked without touching the machine.
    blocked = handle_plan_case_begin(_plan_case_request(current, 1))
    assert blocked.primary_success, blocked.error
    assert blocked.result_payload["state"] == "blocked"
    result = blocked.result_payload["result"]
    assert result["case_outcome"] == "blocked_on_precondition"
    blocker = result["evidence"]["inherit_blocker"]
    assert blocker["predecessor_requirement_id"] == (
        current["roster"][0]["requirement_id"]
    )
    assert blocker["predecessor_requirement_id"] not in {
        case["requirement_id"] for case in old["roster"]
    }


def test_standalone_machine_chain_resets_once_and_restores_after_its_last_case(
    test_db, tmp_path, monkeypatch
):
    from runtime.api.domain.machine_qa_host_test_support import (
        configure_test_machine,
    )
    from runtime.api.domain.machine_qa_test_support import FakeHostControl
    from yoke_core.domain.handlers.machine_qa_plan_case import (
        handle_plan_case_begin,
        handle_plan_case_submit,
    )
    from yoke_core.domain.host_control_runner import (
        clear_host_control_factory,
        register_host_control_factory,
    )
    from yoke_core.domain.machine_qa_local_execution import (
        execute_machine_case_contract,
    )

    configure_test_machine(test_db, tmp_path, monkeypatch)
    plan = _plan(test_db)
    _machine_chain(test_db, plan["id"])
    execution = begin_standalone_execution(
        test_db,
        plan="manual-proof",
        project="yoke",
        actor_id="2",
        session_id="session-machine-plan",
        source_revision=SHA,
    )
    control = FakeHostControl()
    register_host_control_factory(lambda _material: control)
    evidence = []
    resets_before_case = []
    try:
        for ordinal, _case in enumerate(execution["roster"]):
            begun = handle_plan_case_begin(_plan_case_request(execution, ordinal))
            assert begun.primary_success, begun.error
            contract = begun.result_payload["execution"]
            resets_before_case.append(list(contract["baselines"]))
            submission = execute_machine_case_contract(contract)
            evidence.append(submission.payload["results"][0]["evidence"])
            request = _plan_case_request(
                execution, ordinal, "test_machine.plan_case.submit"
            )
            submitted = handle_plan_case_submit(
                request.model_copy(
                    update={"payload": {**request.payload, **submission.payload}}
                )
            )
            assert submitted.primary_success, submitted.error
        # One reset opens the chain; one restore closes it after the last case.
        assert resets_before_case == [["fresh-host"], []]
        assert control.full_reset_calls == 2
        assert "starting_state_restore" not in evidence[0]
        assert evidence[1]["starting_state_restore"]["restored"] is True
        assert evidence[1]["starting_state_restore"]["baseline"] == "fresh-host"
        finish_plan_execution(
            test_db,
            lock_plan_execution(test_db, execution["id"]),
            state="aborted",
            reason="test-complete",
        )
    finally:
        clear_host_control_factory()
