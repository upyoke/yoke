"""A failing Browser assertion records the page it was looking at."""

from __future__ import annotations

from runtime.api.domain.browser_qa_test_helpers import (
    _run_scenario,
    _seed_item,
    _seed_requirement,
)
from runtime.api.fixtures.file_test_db import init_test_db

_ASSERT_ZERO = {"success": False, "error": "found 0"}
_CHECK_STEPS = {
    "steps": [
        {"action": "navigate", "route": "/inbox"},
        {"action": "assert", "target": ".row", "check": "count_gte", "min_count": 1},
    ],
}


def test_failed_assertion_records_page_evidence_without_a_screenshot_step(
    tmp_path,
) -> None:
    """`found 0` leaves a screenshot, so the record names the cause."""
    with init_test_db(tmp_path) as db_path:
        _seed_item(db_path, 410)
        req_id = _seed_requirement(db_path, 410, "browser-check", _CHECK_STEPS)
        run = _run_scenario(
            db_path, 410, requirement_id=req_id,
            assertion_responses={".row": _ASSERT_ZERO},
        ).runs[0]
        assert run.verdict == "fail"
        assert run.execution_status == "captured"
        assert "step_1:found 0" in run.errors
        assert "assertion_failure_capture:" not in run.errors
        assert run.artifact_ids


def test_failed_assertion_names_why_the_page_was_not_captured(tmp_path) -> None:
    with init_test_db(tmp_path) as db_path:
        _seed_item(db_path, 411)
        req_id = _seed_requirement(db_path, 411, "browser-check", _CHECK_STEPS)
        run = _run_scenario(
            db_path, 411, requirement_id=req_id,
            assertion_responses={".row": _ASSERT_ZERO},
            execute_step_responses=[
                {"success": True, "artifacts": []},
                {"success": False, "error": "page_closed"},
            ],
        ).runs[0]
        assert run.verdict == "fail"
        assert run.execution_status == "capture_failed"
        assert "step_1:found 0" in run.errors
        assert "assertion_failure_capture:page_closed" in run.errors
