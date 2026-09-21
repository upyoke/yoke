"""A completed CI run without a pass or fail is not a test failure."""

from __future__ import annotations

from yoke_core.domain.handlers.github_actions_check_ci import _classify


def test_cancelled_run_is_no_verdict() -> None:
    out = _classify(
        {"id": 1, "status": "completed", "conclusion": "cancelled"}
    )
    assert out.state == "no_verdict"
    assert out.conclusion == "cancelled"


def test_skipped_run_is_no_verdict() -> None:
    out = _classify(
        {"id": 1, "status": "completed", "conclusion": "skipped"}
    )
    assert out.state == "no_verdict"
    assert out.conclusion == "skipped"


def test_completed_run_with_empty_conclusion_is_no_verdict() -> None:
    out = _classify({"id": 1, "status": "completed", "conclusion": ""})
    assert out.state == "no_verdict"
    assert out.conclusion is None


def test_failure_conclusion_stays_failed() -> None:
    out = _classify(
        {"id": 1, "status": "completed", "conclusion": "failure"}
    )
    assert out.state == "failed"
    assert out.conclusion == "failure"


def test_success_conclusion_stays_passed() -> None:
    out = _classify(
        {"id": 1, "status": "completed", "conclusion": "success"}
    )
    assert out.state == "passed"


def test_unknown_status_is_no_verdict_not_failed() -> None:
    out = _classify({"id": 1, "status": "requested"})
    assert out.state == "no_verdict"
