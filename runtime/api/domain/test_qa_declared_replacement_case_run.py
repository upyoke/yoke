"""A declared replacement settles through the case runner's own write path.

A Command case records its verdict with ``qa.run.add`` then
``qa.run.complete``, not through a review. The corrected case's pass on that
path must discharge the failed case it replaces on the same transaction, so
the member's stage gate clears without anyone superseding by hand; a failing
or undetermined replacement leaves the failed case blocking.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from runtime.api.domain.test_qa_declared_replacement import (
    MEMBER,
    _failed_with_correction,
    _status,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import ITEM_QA_STAGE
from runtime.api.fixtures.qa_declared_replacement_fixture import requirement_row
from yoke_core.domain.handlers import qa_browser_writes
from yoke_core.domain.qa_plan_execution_state import (
    advance_plan_execution,
    begin_plan_execution,
    finish_plan_execution,
)


def _call(handler: Any, function_id: str, requirement_id: int, payload: dict) -> dict:
    request = FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="2", session_id="member-qa"),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
        payload=payload,
    )
    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        outcome = handler(request)
    assert outcome.primary_success, outcome.error
    return dict(outcome.result_payload or {})


def _run_case(conn: Any, requirement_id: int, verdict: str) -> int:
    """Record the case the way the worktree runner does: add, evidence, complete."""
    run_id = int(
        _call(
            qa_browser_writes.handle_qa_run_add,
            "qa.run.add",
            requirement_id,
            {"performed_by": "worktree_run"},
        )["qa_run_id"]
    )
    conn.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
        "artifact_handle,created_at) VALUES (%s,'command_output','text/plain',%s,%s)",
        (run_id, f"evidence://run-{run_id}", "2026-09-18T00:03:00Z"),
    )
    conn.commit()
    payload: dict[str, Any] = {"run_id": run_id, "verdict": verdict}
    if verdict != "pass":
        payload["verdict_reason"] = f"command case recorded {verdict}"
    _call(
        qa_browser_writes.handle_qa_run_complete,
        "qa.run.complete",
        requirement_id,
        payload,
    )
    return run_id


def _execute_stage(conn: Any, run_id: str, verdict: str) -> None:
    """Run the member's stage roster (the corrected case) to one verdict."""
    execution = begin_plan_execution(
        conn,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
        actor_id="2",
        session_id="member-qa",
    )
    for ordinal, entry in enumerate(execution["roster"]):
        requirement_id = int(entry["requirement_id"])
        qa_run_id = _run_case(conn, requirement_id, verdict)
        advance_plan_execution(
            conn,
            execution,
            ordinal=ordinal,
            requirement_id=requirement_id,
            result={
                "requirement_id": requirement_id,
                "verdict": verdict,
                "case_outcome": "passed" if verdict == "pass" else "failed",
                "run_id": qa_run_id,
            },
        )
    finish_plan_execution(conn, execution, state="completed", reason="test-complete")
    conn.commit()


def test_case_run_pass_discharges_the_failed_case_and_clears_the_stage(test_db) -> None:
    run_id = "run-replacement-case-run-pass"
    failed_id, corrected_id = _failed_with_correction(test_db, run_id)
    assert not _status(test_db, run_id)["accepted"]

    _execute_stage(test_db, run_id, "pass")

    row = requirement_row(test_db, failed_id)
    assert row["superseded_by_requirement_id"] == corrected_id
    assert f"requirement {corrected_id}" in row["supersession_rationale"]
    status = _status(test_db, run_id)
    assert status["accepted"], status["reasons"]


@pytest.mark.parametrize("verdict", ["fail", "undetermined"])
def test_case_run_non_pass_keeps_the_corrected_obligation_blocking(
    test_db, verdict
) -> None:
    run_id = f"run-replacement-case-run-{verdict}"
    failed_id, corrected_id = _failed_with_correction(test_db, run_id)

    _execute_stage(test_db, run_id, verdict)

    row = requirement_row(test_db, failed_id)
    assert row["superseded_by_requirement_id"] is None
    assert row["replacement_requirement_id"] == corrected_id
    status = _status(test_db, run_id)
    assert not status["accepted"]
    assert any(f"#{corrected_id}" in reason for reason in status["reasons"]), status


def test_exact_requirement_correction_materializes_only_its_host_baseline(
    test_db, tmp_path, monkeypatch
):
    from contextlib import nullcontext
    from runtime.api.domain.machine_qa_host_test_support import configure_test_machine
    from runtime.api.fixtures.deployment_scoped_qa_run_fixture import (
        seed_run_standing_on_qa_stage,
        item_qa_stage_definitions,
        record_case_verdict,
    )
    from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
    from yoke_core.domain.handlers.qa_plan_materialize import handle_materialize
    from yoke_core.domain.deployment_qa_stage_materialization import (
        materialize_deployment_qa_stage,
    )
    from yoke_core.domain.qa_plan_execution_roster import ordered_plan_requirements

    configure_test_machine(test_db, tmp_path, monkeypatch)
    case = {
        "case_key": "command-smoke",
        "method_id": "machine-state-check",
        "instructions": "check the host",
        "expected_outcome": "passes",
        "method_config": {
            "test_machine": "mac-mini-lab",
            "assertions": [{"argv": ["/usr/bin/true"]}],
        },
        "host_baselines": ["fresh-host", "shell-preconfigured"],
    }
    original = create_plan(
        test_db, project="yoke", slug="baseline-check", infer_target_environment=False
    )
    replace_plan_cases(test_db, plan_id=original["id"], cases=[case])
    run_id = "run-exact-baseline-correction"
    seed_run_standing_on_qa_stage(
        test_db,
        run_id=run_id,
        project="yoke",
        stages=item_qa_stage_definitions(original["id"]),
        members=(MEMBER,),
        lineage="b" * 40,
    )
    materialize_deployment_qa_stage(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
    )
    rows = test_db.execute(
        "SELECT id,host_baseline FROM qa_requirements WHERE deployment_run_id=%s ORDER BY id",
        (run_id,),
    ).fetchall()
    by_baseline = {row["host_baseline"]: row["id"] for row in rows}
    failed, sibling = by_baseline["fresh-host"], by_baseline["shell-preconfigured"]
    record_case_verdict(test_db, failed, "fail", evidence=True)
    plan = create_plan(
        test_db, project="yoke", slug="exact-correction", infer_target_environment=False
    )
    replace_plan_cases(
        test_db,
        plan_id=plan["id"],
        cases=[{**case, "instructions": "correct this case"}],
    )
    request = FunctionCallRequest(
        function="qa.plan.materialize",
        actor=ActorContext(actor_id="2", session_id="member-qa"),
        target=TargetRef(kind="deployment_run", deployment_run_id=run_id),
        payload={
            "deployment_stage": ITEM_QA_STAGE,
            "deployment_member": f"YOK-{MEMBER}",
            "plan": "exact-correction",
            "replacements": [{"requirement_id": failed}],
        },
    )
    with (
        patch("yoke_core.domain.db_helpers.connect", return_value=nullcontext(test_db)),
        patch(
            "yoke_core.domain.deployment_qa_correction_notice.notify_correction",
            return_value={"delivery": "test"},
        ),
    ):
        outcome = handle_materialize(request)
    assert outcome.primary_success, outcome.error
    corrected = test_db.execute(
        "SELECT id,host_baseline FROM qa_requirements WHERE plan_id=%s AND deployment_run_id=%s",
        (plan["id"], run_id),
    ).fetchall()
    assert len(corrected) == 1 and corrected[0]["host_baseline"] == "fresh-host"
    assert (
        requirement_row(test_db, failed)["replacement_requirement_id"]
        == corrected[0]["id"]
    )
    assert requirement_row(test_db, sibling)["replacement_requirement_id"] is None
    roster = ordered_plan_requirements(
        test_db,
        deployment_run_id=run_id,
        deployment_stage=ITEM_QA_STAGE,
        deployment_member_item_id=MEMBER,
    )
    assert {row["requirement_id"] for row in roster} == {sibling, corrected[0]["id"]}
