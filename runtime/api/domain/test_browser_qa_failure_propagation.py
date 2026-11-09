"""Browser QA — failure propagation."""

from __future__ import annotations


import pytest

from yoke_core.domain import db_backend
from runtime.api.domain.browser_qa_test_helpers import (
    _browser_check_steps,
    _run_scenario,
    _seed_item,
    _seed_requirement,
)
from runtime.api.fixtures.file_test_db import init_test_db


@pytest.fixture
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        yield path


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


class TestFailurePropagation:
    def test_ac13_success_false_step_marks_run_fail(self, db_path: str) -> None:
        """A step returning success:false marks the run verdict=fail."""
        _seed_item(db_path, 100)
        _seed_requirement(
            db_path,
            100,
            "browser-check",
            {
                "base_url": "http://localhost:9999",
                "steps": _browser_check_steps(
                    {"action": "click", "target": "#missing"},
                ),
            },
        )

        result = _run_scenario(
            db_path,
            100,
            execute_step_responses=[
                {"success": True, "artifacts": []},
                {"success": False, "error": "element not found", "artifacts": []},
            ],
        )

        assert result.verdict == "fail"
        assert result.runs[0].verdict == "fail"
        assert "element not found" in result.runs[0].errors

    def test_env_setup_failure_hard_stops(self, db_path: str) -> None:
        """Step returning exit_code=2 aborts remaining requirements."""
        _seed_item(db_path, 100)
        _seed_requirement(
            db_path,
            100,
            "browser-check",
            {
                "base_url": "http://localhost:9999",
                "steps": _browser_check_steps(
                    {"action": "click", "target": "button"},
                ),
            },
        )
        _seed_requirement(
            db_path,
            100,
            "browser-inspection",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    {"action": "screenshot", "capture": True},
                ],
            },
        )

        result = _run_scenario(
            db_path,
            100,
            execute_step_responses=[
                {"success": False, "error": "env_setup_failure", "exit_code": 2}
            ],
        )

        assert result.verdict == "fail"
        # Only the first requirement should have been executed before the
        # env failure aborted the loop.
        assert len(result.runs) == 1
        assert result.runs[0].verdict == "fail"
        assert "env_setup_failure" in result.runs[0].errors
