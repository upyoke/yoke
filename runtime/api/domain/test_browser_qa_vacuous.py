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
            db_path, 300, "browser_smoke",
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

    def test_mixed_skip_and_execute(self, tmp_path: Path, db_path: str) -> None:
        """One malformed + one good → skipped and executed both tracked."""
        _seed_item(db_path, 301)
        _seed_requirement(
            db_path, 301, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    {"action": "screenshot", "capture": True},
                ],
            },
        )
        _seed_requirement(
            db_path, 301, "browser_diff",
            {"url": "https://example.com", "assertions": []},  # no steps array
        )

        # screenshot steps now require artifact paths that exist on disk
        shot_file = tmp_path / "capture.png"
        shot_file.write_bytes(b"PNG")
        result = _run_scenario(
            db_path, 301,
            execute_step_responses=[
                {"success": True, "artifacts": []},  # navigate step
                {"success": True, "artifacts": [str(shot_file)]},  # screenshot step
            ],
        )

        # Good one captured successfully → overall scenario verdict still 'pass'.
        assert result.verdict == "pass"
        assert result.skipped >= 1
        assert result.executed >= 1

        # successful capture leaves verdict NULL (awaiting inspection)
        # and execution_status='captured'. The vacuous-pass-prevention fall-back
        # still records verdict='error' when zero requirements executed, but in
        # this mixed scenario at least one good capture lands.
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
                qa_kind="browser_smoke",
                verdict="pass",
                qa_run_id=42,
                artifacts=["a.png"],
            )
        )
        data = json.loads(result.to_json())
        assert data["verdict"] == "pass"
        assert data["runs"][0]["requirement_id"] == 1
        assert data["runs"][0]["qa_kind"] == "browser_smoke"
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
