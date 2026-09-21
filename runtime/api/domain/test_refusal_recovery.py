"""Refusal reason and recovery are separately checkable."""

from __future__ import annotations

import pytest

from yoke_core.domain.deployment_qa_stage_acceptance import (
    unsettled_acceptance_blocker,
)
from yoke_core.domain.qa_plan_target_reuse_refusal import different_target_refusal
from yoke_core.domain.refusal_recovery import compose_refusal


def test_compose_refusal_requires_recovery_or_escalation() -> None:
    with pytest.raises(ValueError, match="escalate"):
        compose_refusal("the gate failed")
    with pytest.raises(ValueError, match="not both"):
        compose_refusal(
            "the gate failed",
            recovery="retry",
            escalate_to="the operator",
        )


def test_compose_refusal_reports_evaluated_state_and_recovery() -> None:
    text = compose_refusal(
        "the gate failed",
        evaluated="cases passed; digest matched",
        recovery="re-drive the run",
        unavailable=("retry locally",),
    )
    assert "the gate failed" in text
    assert "Evaluated: cases passed; digest matched" in text
    assert "Not available: retry locally" in text
    assert "Recovery: re-drive the run" in text


def test_unsettled_acceptance_names_matched_execution_and_re_drive() -> None:
    text = unsettled_acceptance_blocker(
        execution_id="exec-1", digest="abc123"
    )
    assert "never settled against this deployment target" in text
    assert "completed scoped execution exec-1 matches digest abc123" in text
    assert "no case failed" in text
    assert "re-drive the deployment run" in text
    assert "no member or worker action" in text


def test_different_target_omits_unreachable_remedies_when_passed() -> None:
    text = different_target_refusal(
        subject="YOK-1 transition 'release'",
        requirement_id=28975,
        stored_digest="old",
        expected_digest="new",
        latest_verdict="pass",
        has_runs=True,
        item_bound=True,
    )
    assert "bound to a different execution target" in text
    assert "stored digest old vs current new" in text
    assert "already recorded a passing verdict" in text
    assert "cannot replace requirement 28975" in text
    assert "workers must not create a deployment run" in text
    assert "No reachable recovery from this call" in text
    assert "escalate to the operator" in text
    assert "Recovery:" not in text
