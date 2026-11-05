"""A completed capture awaiting its independent review is not a QA pass.

A deployment QA stage whose case needs an agent verdict captures first and
then waits at ``awaiting_walk_review`` for the reviewer that submits the
bundle. In that window the capture-side session must not be able to write a
verdict of its own onto the requirement, and the stage must say "review
pending" rather than "never run". Once the reviewer submits, the existing
settlement takes over unchanged: a reviewed pass accepts the stage and a
reviewed fail blocks it. Each shape runs for a member-scoped stage and a
run-scoped stage.
"""

from __future__ import annotations

from runtime.api.domain.qa_capture_pending_review_test_support import (
    MEMBER as MEMBER,
    NOW as NOW,
    STAGE as STAGE,
    _acceptance as _acceptance,
    _member as _member,
    _seed_pending as _seed_pending,
    _stages as _stages,
    _submit as _submit,
)


import json
from typing import Any
from unittest.mock import patch

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.deployment_qa_stage_acceptance import (
    STAGE_AWAITING_REVIEW,
    STAGE_CASES_UNRESOLVED,
    STAGE_NOT_RUN,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.handlers import qa_browser_writes, qa_run
from yoke_core.domain.qa_pending_agent_review import (
    pending_review_for_requirement,
)

PENDING_TEXT = "independent agent review is pending"


def _request(function_id: str, requirement_id: int, payload: dict):
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="2", session_id="capture-session"),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
        payload=payload,
    )


def _capture_verdict(conn: Any, requirement_id: int) -> Any:
    return conn.execute(
        "SELECT verdict FROM qa_runs WHERE qa_requirement_id=%s "
        "AND performed_by='browser_substrate'",
        (requirement_id,),
    ).fetchone()["verdict"]


SCOPES = pytest.mark.parametrize("scope", ["item", "run"])


@SCOPES
def test_pending_review_reads_as_review_pending_not_never_run(test_db, scope) -> None:
    run_id = f"run-pending-{scope}"
    execution, bundle, _requirement = _seed_pending(test_db, run_id, scope)

    acceptance = _acceptance(test_db, run_id, scope)
    assert acceptance.state == STAGE_AWAITING_REVIEW != STAGE_NOT_RUN
    # The review-pending reason leads; the case line beside it says only
    # that no verdict exists yet, never that the case passed or failed.
    blocker, case_line = acceptance.blockers
    assert PENDING_TEXT in blocker
    assert "latest verdict is missing" in case_line
    assert str(execution["id"]) in blocker and bundle["bundle_id"] in blocker
    assert "yoke qa plan review-submit" in blocker

    status = deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name=STAGE, member_item_id=_member(scope)
    )
    assert any(PENDING_TEXT in reason for reason in status["reasons"])
    assert not any(
        reason == "no completed scoped QA execution exists"
        for reason in status["reasons"]
    )


@SCOPES
def test_capture_side_verdicts_are_refused_while_review_is_pending(
    test_db, scope
) -> None:
    run_id = f"run-refuse-{scope}"
    _execution, _bundle, requirement_id = _seed_pending(test_db, run_id, scope)
    capture_run_id = int(
        test_db.execute(
            "SELECT id FROM qa_runs WHERE qa_requirement_id=%s", (requirement_id,)
        ).fetchone()["id"]
    )

    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        completed = qa_browser_writes.handle_qa_run_complete(
            _request(
                "qa.run.complete",
                requirement_id,
                {
                    "run_id": capture_run_id,
                    "verdict": "pass",
                    "verdict_reason": "Looked right to the capturing session.",
                    "execution_status": "captured",
                },
            )
        )
        recorded = qa_run.handle_qa_run_record_verdict(
            _request(
                "qa.run.record_verdict",
                requirement_id,
                {
                    "performed_by": "agent",
                    "verdict": "pass",
                    "verdict_reason": "Looked right to the capturing session.",
                },
            )
        )
        added = qa_browser_writes.handle_qa_run_add(
            _request(
                "qa.run.add",
                requirement_id,
                {"performed_by": "browser_substrate", "verdict": "pass"},
            )
        )

    for outcome in (completed, recorded, added):
        assert not outcome.primary_success
        assert outcome.error.code == "policy_violation"
        assert PENDING_TEXT in outcome.error.message
        assert "yoke qa plan review-submit" in outcome.error.message
    assert _capture_verdict(test_db, requirement_id) is None


@SCOPES
def test_reviewed_pass_accepts_the_stage(test_db, scope) -> None:
    run_id = f"run-pass-{scope}"
    execution, bundle, requirement_id = _seed_pending(test_db, run_id, scope)

    _submit(test_db, execution, bundle, requirement_id, "pass")

    assert pending_review_for_requirement(test_db, requirement_id) is None
    assert _capture_verdict(test_db, requirement_id) == "pass"
    status = deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name=STAGE, member_item_id=_member(scope)
    )
    assert not any(PENDING_TEXT in reason for reason in status["reasons"])
    assert _acceptance(test_db, run_id, scope).accepted


@SCOPES
def test_reviewed_fail_blocks_the_stage(test_db, scope) -> None:
    run_id = f"run-fail-{scope}"
    execution, bundle, requirement_id = _seed_pending(test_db, run_id, scope)

    _submit(test_db, execution, bundle, requirement_id, "fail")

    assert pending_review_for_requirement(test_db, requirement_id) is None
    assert _capture_verdict(test_db, requirement_id) == "fail"
    acceptance = _acceptance(test_db, run_id, scope)
    assert acceptance.state == STAGE_CASES_UNRESOLVED
    assert not any(PENDING_TEXT in reason for reason in acceptance.blockers)


def test_verdicts_on_requirements_with_no_pending_review_are_untouched(
    test_db,
) -> None:
    run_id = "run-no-review"
    execution, bundle, requirement_id = _seed_pending(test_db, run_id, "item")
    _submit(test_db, execution, bundle, requirement_id, "pass")

    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        recorded = qa_run.handle_qa_run_record_verdict(
            _request(
                "qa.run.record_verdict",
                requirement_id,
                {
                    "performed_by": "human",
                    "verdict": "pass",
                    "verdict_reason": "Operator confirmation after review.",
                    "raw_result": json.dumps(
                        {"verification_tree": {"head_sha": "e" * 40}}
                    ),
                },
            )
        )
    assert recorded.primary_success, recorded.error
