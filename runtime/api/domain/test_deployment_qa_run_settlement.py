"""Unsuccessful runs retire their QA; late verdicts settle active acceptance."""

import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_qa_admission_execution import (
    _original_requirement,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.completed_delivery import seed_selected_requirement_run
from runtime.api.fixtures.deployment_run_driver_fixture import release_seeded_driver
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.deployment_run_terminalization import terminalize_run_on
from yoke_core.domain.deployment_runs_crud_mutate import cmd_update
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.handlers.qa_run import handle_qa_run_record_verdict
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_terminal_settlement import find_unsettled_records


def test_closure_preserves_execution_that_completes_before_its_lock(monkeypatch):
    from yoke_core.domain import qa_deployment_run_settlement as settlement
    from unittest.mock import Mock

    conn = Mock()
    monkeypatch.setattr(settlement, "_table_exists", lambda *args: True)
    monkeypatch.setattr(settlement, "settled_obligation_sql", lambda *args: "FALSE")
    monkeypatch.setattr(
        settlement,
        "query_rows",
        lambda conn, sql, params: (
            [{"id": "review-finished"}] if "qa_plan_executions" in sql else []
        ),
    )
    monkeypatch.setattr(
        settlement,
        "lock_plan_execution",
        lambda *args: {"id": "review-finished", "state": "completed"},
    )
    finish = Mock()
    monkeypatch.setattr(settlement, "finish_plan_execution", finish)
    monkeypatch.setattr(settlement, "retract_requirements", Mock())
    settlement.settle_unsuccessful_run(conn, "run-failed", reason="runner failed")
    finish.assert_not_called()
    conn.execute.assert_not_called()


def test_failed_run_qa_cleanup_rolls_back_with_the_run(test_db, monkeypatch):
    from yoke_core.domain import deployment_run_terminalization

    run_id, item_id = "run-qa-rollback", 9753
    _seed_run(
        test_db,
        run_id=run_id,
        stages=_stages(_plan(test_db, "rollback-smoke")),
        members=(item_id,),
    )
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=item_id,
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=item_id,
        actor_id="2",
        session_id="rollback-qa",
    )
    monkeypatch.setattr(
        deployment_run_terminalization,
        "_append_event",
        lambda *a, **kw: (_ for _ in ()).throw(RuntimeError("audit unavailable")),
    )
    with pytest.raises(RuntimeError, match="audit unavailable"):
        terminalize_run_on(
            test_db,
            run_id,
            disposition="failed",
            reason="runner stopped",
            actor_id=None,
            session_id="driver",
        )
    test_db.rollback()
    assert (
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id=%s", (run_id,)
        ).fetchone()[0]
        == "executing"
    )
    assert (
        test_db.execute(
            "SELECT state FROM qa_plan_executions WHERE id=%s", (execution["id"],)
        ).fetchone()[0]
        == "active"
    )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE deployment_run_id=%s AND retracted_at IS NOT NULL",
            (run_id,),
        ).fetchone()[0]
        == 0
    )


@pytest.mark.parametrize("disposition", ["failed", "cancelled"])
@pytest.mark.parametrize("writer", ["terminalize", "update"])
def test_run_closure_retires_only_its_open_qa(test_db, disposition, writer):
    run_id, other_run = "run-closed-qa", "run-other-qa"
    item_id = 9750
    plan_id = _plan(test_db, "run-closure-smoke")
    _seed_run(test_db, run_id=run_id, stages=_stages(plan_id), members=(item_id,))
    _seed_run(test_db, run_id=other_run, stages=_stages(plan_id), members=(9751,))
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=item_id,
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=item_id,
        actor_id="2",
        session_id="closing-qa",
    )
    test_db.execute(
        "UPDATE qa_plan_executions SET state='awaiting_walk_review' WHERE id=%s",
        (execution["id"],),
    )
    ids = {}
    for label, owner, blocking in [
        ("open", run_id, "blocking"),
        ("info", run_id, "non_blocking"),
        ("pass", run_id, "blocking"),
        ("other", other_run, "blocking"),
    ]:
        ids[label] = int(
            test_db.execute(
                "INSERT INTO qa_requirements(deployment_run_id,deployment_stage,deployment_member_item_id,qa_kind,qa_phase,blocking_mode,created_at) "
                "VALUES (%s,'item-qa',%s,'ac_verification','post_deploy',%s,'2026-09-14T00:00:00Z') RETURNING id",
                (owner, item_id if owner == run_id else 9751, blocking),
            ).fetchone()[0]
        )
    test_db.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,created_at) VALUES (%s,'agent','ac_verification','pass','2026-09-14T00:03:00Z')",
        (ids["pass"],),
    )
    test_db.commit()
    assert find_unsettled_records(test_db, item_id=item_id)
    if writer == "terminalize":
        terminalize_run_on(
            test_db,
            run_id,
            disposition=disposition,
            reason="runner stopped",
            actor_id=None,
            session_id="driver",
        )
        test_db.commit()
    else:
        assert cmd_update(run_id, "status", disposition) is None
    row = test_db.execute(
        "SELECT state,release_reason,machine_lease_id FROM qa_plan_executions WHERE id=%s",
        (execution["id"],),
    ).fetchone()
    assert row["state"] == "aborted" and run_id in row["release_reason"]
    assert row["machine_lease_id"] is None
    for label in ("open", "info"):
        row = test_db.execute(
            "SELECT retracted_at,retraction_rationale,waived_at FROM qa_requirements WHERE id=%s",
            (ids[label],),
        ).fetchone()
        assert row["retracted_at"] and run_id in row["retraction_rationale"]
        assert row["waived_at"] is None
    for label in ("pass", "other"):
        assert (
            test_db.execute(
                "SELECT retracted_at FROM qa_requirements WHERE id=%s", (ids[label],)
            ).fetchone()[0]
            is None
        )
    assert find_unsettled_records(test_db, item_id=item_id) == []


def test_late_recorded_verdict_links_actual_evidence_and_accepts_stage(test_db):
    item_id, run_id = 9752, "run-late-verdict"
    insert_item(
        test_db,
        id=item_id,
        project_sequence=item_id,
        workflow_id="issue",
        status="done",
    )
    original = _original_requirement(test_db, item_id=item_id, method_id=None)
    plan_id = _plan(test_db, "late-verdict-smoke")
    seed_selected_requirement_run(
        test_db, run_id=run_id, item_id=item_id, requirement_id=original
    )
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
        agent_plan=str(plan_id),
    )
    execution = begin_plan_execution(
        test_db,
        deployment_run_id=run_id,
        deployment_stage="member-qa",
        deployment_member_item_id=item_id,
        actor_id="2",
        session_id="late-verdict",
    )
    _complete_case(test_db, execution)
    release_seeded_driver(test_db, run_id)
    test_db.commit()
    requirement_id = int(
        test_db.execute(
            "SELECT id FROM qa_requirements WHERE deployment_run_id=%s AND method_id IS NULL AND plan_id IS NULL",
            (run_id,),
        ).fetchone()[0]
    )
    # Acceptance is real; external run continuation is separately covered by
    # the auto-completion tests and must not invoke delivery from this fixture.
    with patch(
        "yoke_core.domain.deployment_run_auto_completion.continue_after_settlement",
        return_value=SimpleNamespace(completed=False, failure=""),
    ) as continue_run:
        outcome = handle_qa_run_record_verdict(
            FunctionCallRequest(
                function="qa.run.record_verdict",
                actor=ActorContext(actor_id="2", session_id="late-verdict"),
                target=TargetRef(
                    kind="qa_requirement", qa_requirement_id=requirement_id
                ),
                payload={
                    "performed_by": "agent",
                    "verdict": "pass",
                    "raw_result": json.dumps(
                        {
                            "verification_tree": {"head_sha": "c" * 40},
                            "note": "actual capture reviewed",
                        }
                    ),
                },
            )
        )
    continue_run.assert_called_once()
    assert outcome.primary_success, outcome.error
    raw = json.loads(
        test_db.execute(
            "SELECT raw_result FROM qa_runs WHERE id=%s",
            (outcome.result_payload["qa_run_id"],),
        ).fetchone()[0]
    )
    assert raw["execution_id"] == execution["id"]
    assert raw["evidence_artifact_ids"]
    assert raw["verification_tree"]["head_sha"] == "c" * 40
    assert raw["note"] == "actual capture reviewed"
    # Read durable acceptance without calling the gate: the verdict write itself settled it.
    assert (
        test_db.execute(
            "SELECT r.verdict FROM qa_runs r JOIN qa_requirements q ON q.id=r.qa_requirement_id "
            "WHERE q.deployment_run_id=%s AND q.qa_kind='deployment_stage_acceptance' ORDER BY r.id DESC LIMIT 1",
            (run_id,),
        ).fetchone()[0]
        == "pass"
    )
