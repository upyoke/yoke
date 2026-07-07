"""``qa.cmd_artifact_*`` and ``qa.cmd_baseline_*`` —
artifact creation, listing, baseline candidate vs main, and promotion."""

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


class TestArtifacts:
    def test_add_artifact(self, db_path: str, req_id: int) -> None:
        run_id = qa.cmd_run_add(
            db_path=db_path, requirement_id=req_id,
            executor_type="agent", qa_kind="unit_test",
        )
        art_id = qa.cmd_artifact_add(
            db_path=db_path,
            run_id=run_id,
            artifact_type="screenshot",
            content_type="image/png",
            artifact_handle=json.dumps(
                {"backend": "local", "path": "/tmp/shot.png"}
            ),
            metadata='{"width": 1920}',
        )
        assert art_id > 0

    def test_add_artifact_without_run(self, db_path: str) -> None:
        art_id = qa.cmd_artifact_add(
            db_path=db_path,
            artifact_type="log",
        )
        assert art_id > 0

    def test_artifact_list_all(self, db_path: str, req_id: int) -> None:
        run_id = qa.cmd_run_add(
            db_path=db_path, requirement_id=req_id,
            executor_type="agent", qa_kind="unit_test",
        )
        qa.cmd_artifact_add(db_path=db_path, run_id=run_id, artifact_type="a")
        qa.cmd_artifact_add(db_path=db_path, run_id=run_id, artifact_type="b")
        qa.cmd_artifact_add(db_path=db_path, artifact_type="c")  # no run
        lines = qa.cmd_artifact_list(db_path=db_path)
        assert len(lines) == 3

    def test_artifact_list_filter_by_run(self, db_path: str, req_id: int) -> None:
        run_id = qa.cmd_run_add(
            db_path=db_path, requirement_id=req_id,
            executor_type="agent", qa_kind="unit_test",
        )
        qa.cmd_artifact_add(db_path=db_path, run_id=run_id, artifact_type="a")
        qa.cmd_artifact_add(db_path=db_path, artifact_type="b")  # no run
        lines = qa.cmd_artifact_list(db_path=db_path, run_id=run_id)
        assert len(lines) == 1


class TestBaseline:
    def test_record_candidate(self, db_path: str, tmp_path: Path) -> None:
        screenshot = tmp_path / "shot.png"
        screenshot.write_bytes(b"fake-png")
        art_id = qa.cmd_baseline_record(
            db_path=db_path,
            route="/settings/profile",
            width=1920,
            height=1080,
            branch="feature-x",
            screenshot_path=str(screenshot),
        )
        assert art_id > 0
        # Should be candidate_baseline (not main branch)
        conn = connect_test_db(db_path)
        row = conn.execute("SELECT artifact_type FROM qa_artifacts WHERE id = %s", (art_id,)).fetchone()
        conn.close()
        assert row[0] == "candidate_baseline"

    def test_record_baseline_on_main(self, db_path: str, tmp_path: Path) -> None:
        screenshot = tmp_path / "shot.png"
        screenshot.write_bytes(b"fake-png")
        art_id = qa.cmd_baseline_record(
            db_path=db_path,
            route="/",
            width=1920,
            height=1080,
            branch="main",
            screenshot_path=str(screenshot),
        )
        conn = connect_test_db(db_path)
        row = conn.execute("SELECT artifact_type FROM qa_artifacts WHERE id = %s", (art_id,)).fetchone()
        conn.close()
        assert row[0] == "baseline_image"

    def test_record_with_update_flag(self, db_path: str, tmp_path: Path) -> None:
        screenshot = tmp_path / "shot.png"
        screenshot.write_bytes(b"fake-png")
        art_id = qa.cmd_baseline_record(
            db_path=db_path,
            route="/",
            width=1920,
            height=1080,
            branch="feature-x",
            screenshot_path=str(screenshot),
            update=True,
        )
        conn = connect_test_db(db_path)
        row = conn.execute("SELECT artifact_type FROM qa_artifacts WHERE id = %s", (art_id,)).fetchone()
        conn.close()
        assert row[0] == "baseline_image"

    def test_baseline_list(self, db_path: str, tmp_path: Path) -> None:
        screenshot = tmp_path / "shot.png"
        screenshot.write_bytes(b"fake-png")
        # Record two baselines (on main) and one candidate
        qa.cmd_baseline_record(
            db_path=db_path, route="/a", width=1920, height=1080,
            branch="main", screenshot_path=str(screenshot),
        )
        qa.cmd_baseline_record(
            db_path=db_path, route="/b", width=1920, height=1080,
            branch="main", screenshot_path=str(screenshot),
        )
        qa.cmd_baseline_record(
            db_path=db_path, route="/c", width=1920, height=1080,
            branch="feature", screenshot_path=str(screenshot),
        )
        lines = qa.cmd_baseline_list(db_path=db_path)
        assert len(lines) == 2  # only baseline_image, not candidate

    def test_baseline_get(self, db_path: str, tmp_path: Path) -> None:
        screenshot = tmp_path / "shot.png"
        screenshot.write_bytes(b"fake-png")
        qa.cmd_baseline_record(
            db_path=db_path, route="/dashboard", width=1920, height=1080,
            branch="main", screenshot_path=str(screenshot),
        )
        line = qa.cmd_baseline_get("/dashboard", "1920x1080", db_path=db_path)
        assert "dashboard" in line

    def test_baseline_get_missing_exits(self, db_path: str) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_baseline_get("/missing", "1920x1080", db_path=db_path)
        assert exc.value.code == 1

    def test_baseline_promote(self, db_path: str, tmp_path: Path) -> None:
        screenshot = tmp_path / "shot.png"
        screenshot.write_bytes(b"fake-png")
        art_id = qa.cmd_baseline_record(
            db_path=db_path, route="/settings/profile", width=1920, height=1080,
            branch="feature-x", screenshot_path=str(screenshot),
        )
        # Verify it is a candidate
        conn = connect_test_db(db_path)
        row = conn.execute("SELECT artifact_type FROM qa_artifacts WHERE id = %s", (art_id,)).fetchone()
        assert row[0] == "candidate_baseline"
        conn.close()

        # Promote
        qa.cmd_baseline_promote(art_id, db_path=db_path)

        # Verify it is now a baseline
        conn = connect_test_db(db_path)
        row = conn.execute("SELECT artifact_type, artifact_handle FROM qa_artifacts WHERE id = %s", (art_id,)).fetchone()
        conn.close()
        assert row[0] == "baseline_image"
        handle = json.loads(row[1])
        assert handle["backend"] == "local"
        assert "settings-profile-1920x1080.png" in handle["path"]

    def test_promote_non_candidate_exits(self, db_path: str, tmp_path: Path) -> None:
        screenshot = tmp_path / "shot.png"
        screenshot.write_bytes(b"fake-png")
        art_id = qa.cmd_baseline_record(
            db_path=db_path, route="/", width=1920, height=1080,
            branch="main", screenshot_path=str(screenshot),
        )
        with pytest.raises(SystemExit) as exc:
            qa.cmd_baseline_promote(art_id, db_path=db_path)
        assert exc.value.code == 1

    def test_promote_missing_exits(self, db_path: str) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_baseline_promote(9999, db_path=db_path)
        assert exc.value.code == 1
