"""Terminal QA diagnostics for verdicts that need operator review."""

from yoke_core.domain.qa_terminal_settlement import blocking_requirement_issues


def test_undetermined_requirement_issue_preserves_reason():
    issues = blocking_requirement_issues(
        [
            {
                "id": 41,
                "blocking_mode": "blocking",
                "run_id": 9,
                "verdict": "undetermined",
                "verdict_reason": "The capture omits the checkout confirmation.",
                "completed_at": "2026-08-20T00:00:00Z",
                "case_outcome": "needs_review",
                "method_id": "browser-inspection",
                "requirement_source": "explicit",
            }
        ],
        accepted_shas=(),
        public_ref="YOK-41",
        require_any=True,
    )

    assert len(issues) == 1
    assert issues[0].state == "incomplete"
    assert "checkout confirmation" in issues[0].detail
