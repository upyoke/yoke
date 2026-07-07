"""``qa.cmd_run_add`` / ``_complete`` / ``_list`` / ``_get`` —
run creation guards, executor restrictions, completion semantics, and reads."""

from __future__ import annotations

import json

from pathlib import Path

import pytest

from yoke_core.domain import qa
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.qa_test_helpers import (
    make_basic_requirement,
    make_qa_db_file,
)


@pytest.fixture()
def db_path(tmp_path: Path):
    with make_qa_db_file(tmp_path) as path:
        yield path


@pytest.fixture()
def req_id(db_path: str) -> int:
    return make_basic_requirement(db_path)


class TestQaKindAutoDerive:
    """qa_kind defaults to the requirement's stored kind; mismatches reject."""

    def test_omitted_qa_kind_derives_from_requirement(
        self, db_path: str, req_id: int,
    ) -> None:
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            executor_type="agent",
        )
        assert isinstance(run_id, int)
        conn = connect_test_db(db_path)
        stored = conn.execute(
            "SELECT qa_kind FROM qa_runs WHERE id = %s", (run_id,),
        ).fetchone()[0]
        req_kind = conn.execute(
            "SELECT qa_kind FROM qa_requirements WHERE id = %s", (req_id,),
        ).fetchone()[0]
        conn.close()
        assert stored == req_kind

    def test_mismatched_qa_kind_rejected(
        self, db_path: str, req_id: int,
    ) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_run_add(
                db_path=db_path,
                requirement_id=req_id,
                executor_type="agent",
                qa_kind="ac_verification",  # req_id stores 'unit_test'
            )
        assert exc.value.code == 2

    def test_legacy_alias_normalizes_against_requirement(
        self, db_path: str,
    ) -> None:
        # Requirement stored as canonical implementation_review;
        # caller passes the legacy alias 'review'. The two should
        # normalize to the same value and the run is accepted.
        rid = qa.cmd_requirement_add(
            db_path=db_path, item_id=42,
            qa_kind="implementation_review", qa_phase="verification",
        )
        run_id = qa.cmd_run_add(
            db_path=db_path, requirement_id=rid,
            executor_type="agent", qa_kind="review",
        )
        assert isinstance(run_id, int)


class TestRunAdd:
    def test_add_without_verdict(self, db_path: str, req_id: int) -> None:
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            executor_type="agent",
            qa_kind="unit_test",
        )
        assert isinstance(run_id, int)
        assert run_id > 0
        # No verdict => completed_at is NULL
        conn = connect_test_db(db_path)
        row = conn.execute("SELECT verdict, completed_at FROM qa_runs WHERE id = %s", (run_id,)).fetchone()
        conn.close()
        assert row[0] is None
        assert row[1] is None

    def test_add_with_verdict(self, db_path: str, req_id: int) -> None:
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            executor_type="agent",
            qa_kind="unit_test",
            verdict="pass",
        )
        conn = connect_test_db(db_path)
        row = conn.execute("SELECT verdict, completed_at FROM qa_runs WHERE id = %s", (run_id,)).fetchone()
        conn.close()
        assert row[0] == "pass"
        assert row[1] is not None  # completed_at set

    def test_agent_not_allowed_for_browser_smoke(self, db_path: str, req_id: int) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_run_add(
                db_path=db_path,
                requirement_id=req_id,
                executor_type="agent",
                qa_kind="browser_smoke",
            )
        assert exc.value.code == 2

    def test_agent_not_allowed_for_browser_diff(self, db_path: str, req_id: int) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_run_add(
                db_path=db_path,
                requirement_id=req_id,
                executor_type="agent",
                qa_kind="browser_diff",
            )
        assert exc.value.code == 2

    def test_agent_not_allowed_for_screenshot_evidence(self, db_path: str) -> None:
        rid = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=10,
            qa_kind="ac_verification",
            qa_phase="verification",
            success_policy='{"requires_screenshot_evidence": true}',
        )
        with pytest.raises(SystemExit) as exc:
            qa.cmd_run_add(
                db_path=db_path,
                requirement_id=rid,
                executor_type="agent",
                qa_kind="ac_verification",
            )
        assert exc.value.code == 2

    def test_optional_fields(self, db_path: str, req_id: int) -> None:
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            executor_type="agent",
            qa_kind="unit_test",
            verdict="pass",
            score=0.95,
            confidence=0.8,
            raw_result="all green",
            duration_ms=1234,
        )
        conn = connect_test_db(db_path)
        row = conn.execute("SELECT score, confidence, raw_result, duration_ms FROM qa_runs WHERE id = %s", (run_id,)).fetchone()
        conn.close()
        assert row[0] == 0.95
        assert row[1] == 0.8
        assert row[2] == "all green"
        assert row[3] == 1234

    def test_legacy_review_alias_normalized_on_write(self, db_path: str) -> None:
        rid = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=10,
            qa_kind="review",
            qa_phase="validation",
        )
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=rid,
            executor_type="agent",
            qa_kind="review",
            verdict="pass",
        )
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT qa_kind FROM qa_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
        conn.close()
        assert row[0] == "implementation_review"

    def test_artifact_path_creates_linked_artifact(self, db_path: str, req_id: int, tmp_path: Path) -> None:
        """--artifact-path creates a qa_artifact linked to the new run."""
        screenshot = tmp_path / "shot.png"
        screenshot.write_bytes(b"\x89PNG")
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            executor_type="browser_substrate",
            qa_kind="unit_test",
            verdict="pass",
            artifact_path=str(screenshot),
        )
        conn = connect_test_db(db_path)
        art = conn.execute(
            "SELECT artifact_type, content_type, artifact_handle FROM qa_artifacts WHERE qa_run_id = %s",
            (run_id,),
        ).fetchone()
        conn.close()
        assert art is not None
        assert art["artifact_type"] == "screenshot"
        assert art["content_type"] == "image/png"
        handle = json.loads(art["artifact_handle"])
        assert handle["backend"] == "local"
        assert handle["path"] == str(screenshot)

    def test_artifact_path_none_creates_no_artifact(self, db_path: str, req_id: int) -> None:
        """Without --artifact-path, no artifact row is created."""
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            executor_type="agent",
            qa_kind="unit_test",
            verdict="pass",
        )
        conn = connect_test_db(db_path)
        count = conn.execute(
            "SELECT COUNT(*) FROM qa_artifacts WHERE qa_run_id = %s",
            (run_id,),
        ).fetchone()[0]
        conn.close()
        assert count == 0


class TestRunComplete:
    def test_complete_sets_verdict(self, db_path: str, req_id: int) -> None:
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            executor_type="agent",
            qa_kind="unit_test",
        )
        result = qa.cmd_run_complete(db_path=db_path, run_id=run_id, verdict="pass")
        assert result == run_id

        conn = connect_test_db(db_path)
        row = conn.execute("SELECT verdict, completed_at FROM qa_runs WHERE id = %s", (run_id,)).fetchone()
        conn.close()
        assert row[0] == "pass"
        assert row[1] is not None

    def test_complete_with_optional_fields(self, db_path: str, req_id: int) -> None:
        run_id = qa.cmd_run_add(
            db_path=db_path, requirement_id=req_id,
            executor_type="agent", qa_kind="unit_test",
        )
        qa.cmd_run_complete(
            db_path=db_path, run_id=run_id, verdict="fail",
            raw_result="test X failed", duration_ms=500,
        )
        conn = connect_test_db(db_path)
        row = conn.execute("SELECT verdict, raw_result, duration_ms FROM qa_runs WHERE id = %s", (run_id,)).fetchone()
        conn.close()
        assert row[0] == "fail"
        assert row[1] == "test X failed"
        assert row[2] == 500

    def test_complete_missing_run_exits(self, db_path: str) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_run_complete(db_path=db_path, run_id=9999, verdict="pass")
        assert exc.value.code == 1


class TestRunListGet:
    def test_run_list_all(self, db_path: str, req_id: int) -> None:
        # qa_kind auto-derived from the requirement's stored kind.
        qa.cmd_run_add(db_path=db_path, requirement_id=req_id, executor_type="a")
        qa.cmd_run_add(db_path=db_path, requirement_id=req_id, executor_type="b")
        lines = qa.cmd_run_list(db_path=db_path)
        assert len(lines) == 2

    def test_run_list_filter(self, db_path: str, req_id: int) -> None:
        qa.cmd_run_add(db_path=db_path, requirement_id=req_id, executor_type="a")
        # Add a second requirement and run; both use auto-derivation.
        rid2 = qa.cmd_requirement_add(db_path=db_path, item_id=99, qa_kind="z", qa_phase="verification")
        qa.cmd_run_add(db_path=db_path, requirement_id=rid2, executor_type="b")
        lines = qa.cmd_run_list(db_path=db_path, requirement_id=req_id)
        assert len(lines) == 1

    def test_run_get(self, db_path: str, req_id: int) -> None:
        run_id = qa.cmd_run_add(db_path=db_path, requirement_id=req_id, executor_type="a")
        line = qa.cmd_run_get(run_id, db_path=db_path)
        assert line.startswith(str(run_id))

    def test_run_get_missing_exits(self, db_path: str) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_run_get(9999, db_path=db_path)
        assert exc.value.code == 1
