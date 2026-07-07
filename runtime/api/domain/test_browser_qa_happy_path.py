"""Browser QA — happy path and failure-propagation suites."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict
from unittest import mock

import pytest

from yoke_core.domain import browser_qa, db_backend
from yoke_core.domain.qa_artifact_handle import parse_handle
from yoke_core.domain.qa_artifact_ops import linked_artifact_handle
from yoke_core.domain.qa_artifacts import artifact_directory
from yoke_core.domain.browser_qa_test_helpers import (
    _FakeRunRecorder,
    _fetch_context_from_test_db,
    _run_scenario,
    _seed_item,
    _seed_requirement,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db


@pytest.fixture
def db_path(tmp_path):
    with init_test_db(tmp_path) as path:
        yield path


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


# ---------------------------------------------------------------------------
# Happy path and run recording
# ---------------------------------------------------------------------------

class TestHappyPath:
    def test_ac6_successful_run_records_qa_run_with_browser_substrate(
        self, tmp_path: Path, db_path: str
    ) -> None:
        """AC-6/7/8/11: happy path records qa_run with executor_type='browser_substrate'."""
        _seed_item(db_path, 100)
        req_id = _seed_requirement(
            db_path, 100, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    {"action": "screenshot", "capture": True, "label": "home"},
                ],
            },
        )

        # screenshot steps now require artifact paths that exist on disk
        shot_file = tmp_path / "home.png"
        shot_file.write_bytes(b"PNG")
        result = _run_scenario(
            db_path, 100,
            execute_step_responses=[
                {"success": True, "artifacts": []},  # navigate step — no artifact expected
                {"success": True, "artifacts": [str(shot_file)]},  # screenshot step
            ],
        )

        # scenario-level verdict stays 'pass' for capture success.
        # Per-run verdict is now empty (None rendered as '' in RunResult) with
        # execution_status='captured' until inspection fires verdict.
        assert result.verdict == "pass"
        assert result.executed == 1
        assert len(result.runs) == 1
        assert result.runs[0].qa_kind == "browser_smoke"
        assert result.runs[0].verdict == ""
        assert result.runs[0].execution_status == "captured"

        # Check qa_run was recorded with execution_status and NULL verdict.
        conn = connect_test_db(db_path)
        p = _placeholder(conn)
        row = conn.execute(
            "SELECT executor_type, verdict, execution_status FROM qa_runs "
            f"WHERE qa_requirement_id = {p}",
            (req_id,),
        ).fetchone()
        conn.close()
        assert row is not None
        assert row[0] == "browser_substrate"
        assert row[1] is None
        assert row[2] == "captured"

    def test_artifacts_use_scratch_storage_tree(
        self,
        tmp_path: Path,
        db_path: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Artifacts land under the project scratch storage tree."""
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
        _seed_item(db_path, 100)
        req_id = _seed_requirement(
            db_path,
            100,
            "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [
                    {"action": "navigate", "route": "/"},
                    {"action": "screenshot", "capture": True, "label": "home"},
                ],
            },
        )
        recorder = _FakeRunRecorder(db_path)
        captured: Dict[str, Any] = {}

        def _fake_step(
            _step: Dict[str, Any],
            _base_url: str,
            artifact_dir: str,
            run_id: int,
            item_id: int,
            project: str,
            _route: str,
            _step_idx: int,
        ) -> Dict[str, Any]:
            captured["artifact_dir"] = artifact_dir
            captured["run_id"] = run_id
            captured["item_id"] = item_id
            captured["project"] = project
            if _step.get("action") != "screenshot":
                return {"success": True, "artifacts": []}
            shot = Path(artifact_dir) / "home.png"
            shot.parent.mkdir(parents=True, exist_ok=True)
            shot.write_bytes(b"PNG")
            return {"success": True, "artifacts": [str(shot)]}

        def _fake_context(item_id, project, expected_branch=None):
            return _fetch_context_from_test_db(
                db_path, item_id, project, expected_branch,
            )

        patches = [
            mock.patch.object(browser_qa, "_fetch_browser_context", side_effect=_fake_context),
            mock.patch.object(browser_qa, "_validate_reachability", return_value=None),
            mock.patch.object(browser_qa, "_ensure_daemon_running", return_value=None),
            mock.patch.object(browser_qa, "_record_run", side_effect=recorder.record_run),
            mock.patch.object(browser_qa, "_complete_run", side_effect=recorder.complete_run),
            mock.patch.object(browser_qa, "_record_artifact", side_effect=recorder.record_artifact),
            mock.patch.object(browser_qa, "_presign_artifact", return_value=None),
            mock.patch.object(browser_qa, "_execute_step", side_effect=_fake_step),
        ]

        for patcher in patches:
            patcher.start()
        try:
            result = browser_qa.execute_scenario(
                item_id=100,
                project="testproj",
                base_url="http://localhost:9999",
            )
        finally:
            for patcher in reversed(patches):
                patcher.stop()

        assert result.verdict == "pass"
        assert result.executed == 1
        assert captured["project"] == "testproj"
        assert captured["item_id"] == 100
        expected_dir = artifact_directory(
            "testproj", 100, captured["run_id"], create=False
        )
        assert Path(captured["artifact_dir"]) == expected_dir
        assert (expected_dir / "home.png").is_file()

        conn = connect_test_db(db_path)
        p = _placeholder(conn)
        row = conn.execute(
            f"SELECT artifact_handle FROM qa_artifacts WHERE qa_run_id = {p}",
            (captured["run_id"],),
        ).fetchone()
        conn.close()

        assert row is not None
        handle = parse_handle(row[0])
        # No artifacts bucket configured -> explicit local handle on the
        # scratch capture path.
        assert handle["backend"] == "local"
        assert handle["path"] == str(
            artifact_directory(
                "testproj", 100, captured["run_id"], create=False
            ) / "home.png"
        )

        # capture success leaves verdict NULL (awaiting inspection)
        # and stamps execution_status='captured'.
        conn = connect_test_db(db_path)
        p = _placeholder(conn)
        qa_row = conn.execute(
            "SELECT executor_type, verdict, execution_status FROM qa_runs "
            f"WHERE qa_requirement_id = {p}",
            (req_id,),
        ).fetchone()
        conn.close()
        assert (qa_row[0], qa_row[1], qa_row[2]) == ("browser_substrate", None, "captured")
        assert result.runs[0].artifacts == [str(expected_dir / "home.png")]

        conn = connect_test_db(db_path)
        p = _placeholder(conn)
        raw_row = conn.execute(
            f"SELECT raw_result FROM qa_runs WHERE qa_requirement_id = {p}",
            (req_id,),
        ).fetchone()
        conn.close()
        assert raw_row is not None
        payload = json.loads(raw_row[0])
        assert payload["artifacts"] == [str(expected_dir / "home.png")]

    def test_linked_manual_artifact_copies_to_scratch_storage(
        self,
        tmp_path: Path,
        db_path: str,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """One-step manual artifact evidence is copied into scratch storage."""
        monkeypatch.setenv("YOKE_SCRATCH_ROOT", str(tmp_path / "scratch"))
        _seed_item(db_path, 100)
        req_id = _seed_requirement(
            db_path,
            100,
            "browser_smoke",
            {"steps": [{"action": "screenshot", "capture": True}]},
        )
        source = tmp_path / "manual.png"
        source.write_bytes(b"PNG")

        conn = connect_test_db(db_path)
        try:
            handle_text = linked_artifact_handle(
                conn,
                requirement_id=req_id,
                run_id=77,
                artifact_path=str(source),
            )
        finally:
            conn.close()

        handle = parse_handle(handle_text)
        assert handle["backend"] == "local"
        expected_file = Path(handle["path"])
        assert expected_file == artifact_directory(
            "yoke", 100, 77, create=False
        ) / "manual.png"
        assert expected_file.read_bytes() == b"PNG"

    def test_ac3_only_browser_kinds_are_executed(self, db_path: str) -> None:
        """AC-3: non-browser qa_kinds (simulation) are not touched by execute_scenario."""
        _seed_item(db_path, 100)
        _seed_requirement(
            db_path, 100, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [{"action": "navigate"}],
            },
        )
        # Simulate a non-browser requirement (different qa_kind).
        conn = connect_test_db(db_path)
        conn.execute(
            """
            INSERT INTO qa_requirements (item_id, qa_kind, qa_phase, blocking_mode, requirement_source, created_at)
            VALUES (100, 'simulation', 'verification', 'blocking', 'explicit', '2026-01-01T00:00:00Z')
            """
        )
        conn.commit()
        conn.close()

        result = _run_scenario(
            db_path, 100,
            execute_step_responses=[{"success": True, "artifacts": []}],
        )
        assert result.verdict == "pass"

        conn = connect_test_db(db_path)
        kinds = [r[0] for r in conn.execute("SELECT qa_kind FROM qa_runs").fetchall()]
        conn.close()
        # Only browser kinds should have been executed; simulation must not appear.
        assert "simulation" not in kinds
        assert "browser_smoke" in kinds


# ---------------------------------------------------------------------------
# Failure propagation
# ---------------------------------------------------------------------------

class TestFailurePropagation:
    def test_ac13_success_false_step_marks_run_fail(self, db_path: str) -> None:
        """AC-13: a step returning success:false marks the run verdict=fail."""
        _seed_item(db_path, 100)
        _seed_requirement(
            db_path, 100, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [{"action": "click", "selector": "#missing"}],
            },
        )

        result = _run_scenario(
            db_path, 100,
            execute_step_responses=[
                {"success": False, "error": "element not found", "artifacts": []}
            ],
        )

        assert result.verdict == "fail"
        assert result.runs[0].verdict == "fail"
        assert "element not found" in result.runs[0].errors

    def test_env_setup_failure_hard_stops(self, db_path: str) -> None:
        """Step returning exit_code=2 aborts remaining requirements."""
        _seed_item(db_path, 100)
        _seed_requirement(
            db_path, 100, "browser_smoke",
            {
                "base_url": "http://localhost:9999",
                "steps": [{"action": "navigate"}, {"action": "click"}],
            },
        )
        _seed_requirement(
            db_path, 100, "browser_diff",
            {
                "base_url": "http://localhost:9999",
                "steps": [{"action": "navigate"}],
            },
        )

        result = _run_scenario(
            db_path, 100,
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
