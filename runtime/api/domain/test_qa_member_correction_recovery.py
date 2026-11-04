"""The printed member recovery refreshes frozen content before grading it."""

from contextlib import nullcontext
import re
import shlex

import pytest

from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
    ITEM_QA_STAGE, record_case_verdict, seed_member_qa_case,
)
from yoke_cli.commands.adapters import qa_execution_subjects
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest
from yoke_core.domain import qa_plan_execution_cli
from yoke_core.domain.deployment_qa_stage_materialization import materialize_deployment_qa_stage
from yoke_core.domain.handlers.qa_plan_materialize import handle_rematerialize
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_requirement_replacement import QaReplacementError, declare_replacements


def test_printed_commands_grade_the_corrected_member_case(test_db, monkeypatch):
    member, run_id = 9871, "run-member-corrected-recovery"
    failed = seed_member_qa_case(test_db, run_id=run_id, member_item_id=member)
    test_db.execute(
        "UPDATE items SET deployment_flow=(SELECT flow FROM deployment_runs WHERE id=%s) "
        "WHERE id=%s", (run_id, member),
    )
    record_case_verdict(test_db, failed, "fail", evidence=True)
    row = test_db.execute(
        "SELECT plan_id FROM qa_requirements WHERE id=%s", (failed,)
    ).fetchone()
    plan = row["plan_id"]
    test_db.execute(
        "UPDATE qa_plan_cases SET instructions=%s WHERE plan_id=%s",
        ("run the corrected smoke command", plan),
    )
    test_db.commit()
    subject = dict(
        deployment_run_id=run_id, deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=member,
    )
    selected = materialize_deployment_qa_stage(test_db, **subject)
    assert selected["existing_requirement_ids"] == [failed]
    with pytest.raises(QaReplacementError) as caught:
        declare_replacements(
            test_db, [{"requirement_id": failed, "case_key": "command-smoke"}],
            materialized_requirement_ids=[failed],
        )
    commands = re.findall(r"`(yoke qa plan [^`]+)`", str(caught.value))
    assert len(commands) == 2
    assert f"--item YOK-{member} --stage {ITEM_QA_STAGE} --plan {plan} --project yoke" in commands[0]
    monkeypatch.setattr(
        "yoke_core.domain.db_helpers.connect", lambda: nullcontext(test_db)
    )

    def dispatch(**kwargs):
        target = kwargs["target"].model_copy(update={"item_id": member})
        outcome = handle_rematerialize(FunctionCallRequest(
            function=kwargs["function_id"], target=target,
            actor=ActorContext(actor_id="2", session_id="member-recovery"),
            payload=kwargs["payload"],
        ))
        assert outcome.primary_success, outcome.error
        return 0

    monkeypatch.setattr(qa_execution_subjects, "dispatch_and_emit", dispatch)
    assert qa_execution_subjects.qa_plan_rematerialize(shlex.split(commands[0])[4:]) == 0

    def execute(**kwargs):
        assert kwargs["public_ref"] == f"YOK-{member}"
        assert kwargs["deployment_stage"] == ITEM_QA_STAGE
        assert kwargs["plan"] == str(plan)
        assert kwargs["project"] == "yoke"
        assert not kwargs["replacements"]
        materialize_deployment_qa_stage(test_db, **subject, agent_plan=kwargs["plan"])
        execution = begin_plan_execution(
            test_db, **subject, actor_id="2", session_id="member-recovery",
        )
        assert len(execution["roster"]) == 1
        corrected = execution["roster"][0]
        assert corrected["requirement_id"] != failed
        assert corrected["instructions"] == "run the corrected smoke command"
        record_case_verdict(test_db, corrected["requirement_id"], "pass", evidence=True)
        return {"state": "passed"}

    monkeypatch.setattr(qa_plan_execution_cli, "execute_plan", execute)
    assert qa_plan_execution_cli.run(shlex.split(commands[1])[4:]) == 0
    verdicts = test_db.execute(
        "SELECT qa_requirement_id,verdict FROM qa_runs WHERE qa_requirement_id IN "
        "(SELECT id FROM qa_requirements WHERE deployment_run_id=%s) ORDER BY id",
        (run_id,),
    ).fetchall()
    assert [(r["qa_requirement_id"], r["verdict"]) for r in verdicts][0] == (failed, "fail")
    assert verdicts[-1]["qa_requirement_id"] != failed
    assert verdicts[-1]["verdict"] == "pass"
