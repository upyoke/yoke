from __future__ import annotations

import pytest

from yoke_core.domain.qa_plan_review_submission import _reviewed_execution_state


@pytest.mark.parametrize(
    ("prior_outcome", "prior_verdict", "expected"),
    [
        ("failed", "fail", "failed"),
        ("blocked_on_precondition", None, "blocked_on_precondition"),
        ("passed", "pass", "passed"),
    ],
)
def test_review_settlement_preserves_every_deterministic_case(
    prior_outcome: str,
    prior_verdict: str | None,
    expected: str,
) -> None:
    recorded = [
        {
            "requirement_id": 41,
            "result": {
                "case_outcome": prior_outcome,
                "verdict": prior_verdict,
            },
        },
        {
            "requirement_id": 42,
            "result": {
                "case_outcome": "needs_review",
                "verdict": None,
            },
        },
    ]

    assert (
        _reviewed_execution_state(
            recorded,
            {42: ("pass", "The inspected frame is correct.")},
        )
        == expected
    )
