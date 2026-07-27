"""Browser QA — vacuous-pass prevention and ScenarioResult JSON shape."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_core.domain import browser_qa
from yoke_core.domain.browser_qa_test_helpers import (
    _run_scenario,
    _seed_item,
    _seed_requirement,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        yield path


# ---------------------------------------------------------------------------
# Vacuous pass prevention
# ---------------------------------------------------------------------------

class TestVacuousPassPrevention:
    def test_all_skipped_prevents_vacuous_pass(self, db_path: str) -> None:
        """Malformed success_policy (no steps) → verdict=error."""
        _seed_item(db_path, 300)
        _seed_requirement(
            db_path, 300, "browser-check",
            {"url": "https://example.com/login", "assertions": []},  # no "steps" array
        )

        result = _run_scenario(db_path, 300)

        assert result.verdict == "error"
        assert result.note == "vacuous_pass_prevented"
        assert result.skipped == 1
        assert result.executed == 0

        # A qa_run with verdict=error should have been recorded for the skipped requirement.
        conn = connect_test_db(db_path)
        err_count = conn.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE verdict = 'error'"
        ).fetchone()[0]
        conn.close()
        assert err_count == 1

    def test_action_only_browser_check_prevents_vacuous_pass(
        self, db_path: str,
    ) -> None:
        """Navigation success cannot stand in for a Browser assertion."""
        _seed_item(db_path, 302)
        _seed_requirement(
            db_path,
            302,
            "browser-check",
            {"steps": [{"action": "navigate", "route": "/"}]},
        )

        result = _run_scenario(db_path, 302)

        assert result.verdict == "error"
        assert result.note == "vacuous_pass_prevented"
        assert result.executed == 0
        assert result.skipped == 1
        assert "assertion_missing" in result.runs[0].errors

    def test_browser_inspection_without_capture_prevents_vacuous_review(
        self, db_path: str,
    ) -> None:
        """Inspection needs evidence before it can enter human judgment."""
        _seed_item(db_path, 303)
        _seed_requirement(
            db_path,
            303,
            "browser-inspection",
            {"steps": [{"action": "navigate", "route": "/"}]},
        )

        result = _run_scenario(db_path, 303)

        assert result.verdict == "error"
        assert result.note == "vacuous_pass_prevented"
        assert result.executed == 0
        assert result.skipped == 1
        assert "capture_missing" in result.runs[0].errors

    def test_materialized_cases_execute_independently(
        self, tmp_path: Path, db_path: str,
    ) -> None:
        """A malformed case cannot alter a sibling case's execution."""
        _seed_item(db_path, 301)
        good_id = _seed_requirement(
            db_path, 301, "browser-check",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    {
                        "action": "assert",
                        "target": "main",
                        "check": "visible",
                    },
                    {"action": "screenshot", "capture": True},
                ],
            },
        )
        malformed_id = _seed_requirement(
            db_path, 301, "browser-inspection",
            {"url": "https://example.com", "assertions": []},  # no steps array
        )

        # screenshot steps now require artifact paths that exist on disk
        shot_file = tmp_path / "capture.png"
        shot_file.write_bytes(b"PNG")
        good_result = _run_scenario(
            db_path, 301, requirement_id=good_id,
            execute_step_responses=[
                {"success": True, "artifacts": []},  # navigate step
                {"success": True, "artifacts": [str(shot_file)]},  # screenshot step
            ],
        )
        malformed_result = _run_scenario(
            db_path, 301, requirement_id=malformed_id,
        )

        assert good_result.verdict == "pass"
        assert good_result.executed == 1
        assert good_result.skipped == 0
        assert malformed_result.executed == 0
        assert malformed_result.skipped == 1

        conn = connect_test_db(db_path)
        captured_count = conn.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE execution_status = 'captured'"
        ).fetchone()[0]
        err_count = conn.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE verdict = 'error'"
        ).fetchone()[0]
        conn.close()
        assert captured_count >= 1
        assert err_count >= 1


# ---------------------------------------------------------------------------
# JSON output shape
# ---------------------------------------------------------------------------

class TestScenarioResultSerialization:
    def test_to_json_shape_for_passing_result(self) -> None:
        result = browser_qa.ScenarioResult(verdict="pass")
        result.runs.append(
            browser_qa.RunResult(
                requirement_id=1,
                qa_kind="plan_case",
                verdict="pass",
                qa_run_id=42,
                artifacts=["a.png"],
            )
        )
        data = json.loads(result.to_json())
        assert data["verdict"] == "pass"
        assert data["runs"][0]["requirement_id"] == 1
        assert data["runs"][0]["qa_kind"] == "plan_case"
        assert data["runs"][0]["verdict"] == "pass"
        assert data["runs"][0]["qa_run_id"] == 42
        assert data["runs"][0]["artifacts"] == ["a.png"]

    def test_to_json_includes_skipped_counts_when_nonzero(self) -> None:
        result = browser_qa.ScenarioResult(verdict="error", skipped=2, executed=0, note="vacuous_pass_prevented")
        data = json.loads(result.to_json())
        assert data["verdict"] == "error"
        assert data["skipped"] == 2
        assert data["executed"] == 0
        assert data["note"] == "vacuous_pass_prevented"
