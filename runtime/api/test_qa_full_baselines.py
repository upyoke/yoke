"""baseline-record/list/get/promote — visual baseline lifecycle.

Covers ``cmd_baseline_record`` (candidate vs ``baseline_image`` selection by
branch and ``--update`` flag), ``cmd_baseline_list``, ``cmd_baseline_get`` by
route+viewport, and the ``cmd_baseline_promote`` candidate-to-baseline path.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import qa
from runtime.api.qa_full_test_helpers import conn_with_rows, make_qa_db_file


@pytest.fixture()
def db_path(tmp_path):
    with make_qa_db_file(tmp_path) as path:
        yield path


def _conn(db_path: str):
    return conn_with_rows(db_path)


class TestBaselineRecord:
    """cmd_baseline_record: record baseline/candidate images."""

    def test_record_candidate(self, db_path, capsys, tmp_path):
        shot = tmp_path / "shot.png"
        shot.write_bytes(b"\x89PNG")  # minimal PNG header

        art_id = qa.cmd_baseline_record(
            db_path=db_path,
            route="/",
            width=1920,
            height=1080,
            screenshot_path=str(shot),
        )
        assert art_id >= 1

        conn = _conn(db_path)
        row = conn.execute("SELECT artifact_type, artifact_handle FROM qa_artifacts WHERE id=%s", (art_id,)).fetchone()
        conn.close()
        assert row["artifact_type"] == "candidate_baseline"
        handle = json.loads(row["artifact_handle"])
        assert handle["backend"] == "local"
        assert "1920x1080" in handle["path"]

    def test_record_baseline_from_main(self, db_path, capsys, tmp_path):
        shot = tmp_path / "shot.png"
        shot.write_bytes(b"\x89PNG")

        art_id = qa.cmd_baseline_record(
            db_path=db_path,
            route="/settings",
            width=1920,
            height=1080,
            branch="main",
            screenshot_path=str(shot),
        )
        conn = _conn(db_path)
        row = conn.execute("SELECT artifact_type FROM qa_artifacts WHERE id=%s", (art_id,)).fetchone()
        conn.close()
        assert row["artifact_type"] == "baseline_image"

    def test_record_baseline_with_update_flag(self, db_path, capsys, tmp_path):
        shot = tmp_path / "shot.png"
        shot.write_bytes(b"\x89PNG")

        art_id = qa.cmd_baseline_record(
            db_path=db_path,
            route="/",
            width=1920,
            height=1080,
            screenshot_path=str(shot),
            update=True,
        )
        conn = _conn(db_path)
        row = conn.execute("SELECT artifact_type FROM qa_artifacts WHERE id=%s", (art_id,)).fetchone()
        conn.close()
        assert row["artifact_type"] == "baseline_image"


class TestBaselineList:
    """cmd_baseline_list: list baseline_image artifacts."""

    def test_list_baselines(self, db_path, capsys, tmp_path):
        shot = tmp_path / "shot.png"
        shot.write_bytes(b"\x89PNG")

        qa.cmd_baseline_record(
            db_path=db_path, route="/", width=1920, height=1080,
            branch="main", screenshot_path=str(shot),
        )
        qa.cmd_baseline_record(
            db_path=db_path, route="/settings", width=1920, height=1080,
            branch="main", screenshot_path=str(shot),
        )
        # candidate (not a baseline_image)
        qa.cmd_baseline_record(
            db_path=db_path, route="/other", width=1920, height=1080,
            screenshot_path=str(shot),
        )
        capsys.readouterr()
        lines = qa.cmd_baseline_list(db_path=db_path)
        assert len(lines) == 2  # only baseline_images


class TestBaselineGet:
    """cmd_baseline_get: retrieve baseline by route+viewport."""

    def test_get_existing(self, db_path, capsys, tmp_path):
        shot = tmp_path / "shot.png"
        shot.write_bytes(b"\x89PNG")

        qa.cmd_baseline_record(
            db_path=db_path, route="/", width=1920, height=1080,
            branch="main", screenshot_path=str(shot),
        )
        capsys.readouterr()
        line = qa.cmd_baseline_get("/", "1920x1080", db_path=db_path)
        assert "1920x1080" in line

    def test_get_not_found_exits(self, db_path):
        with pytest.raises(SystemExit):
            qa.cmd_baseline_get("/nonexistent", "1920x1080", db_path=db_path)


class TestBaselinePromote:
    """cmd_baseline_promote: promote candidate to baseline."""

    def test_promote(self, db_path, capsys, tmp_path):
        shot = tmp_path / "shot.png"
        shot.write_bytes(b"\x89PNG")

        art_id = qa.cmd_baseline_record(
            db_path=db_path, route="/promote-test", width=1920, height=1080,
            screenshot_path=str(shot),
        )
        capsys.readouterr()
        qa.cmd_baseline_promote(art_id, db_path=db_path)
        captured = capsys.readouterr()
        assert "Promoted" in captured.out

        conn = _conn(db_path)
        row = conn.execute("SELECT artifact_type FROM qa_artifacts WHERE id=%s", (art_id,)).fetchone()
        conn.close()
        assert row["artifact_type"] == "baseline_image"

    def test_promote_not_candidate_exits(self, db_path, capsys, tmp_path):
        """Cannot promote a baseline_image (already promoted)."""
        shot = tmp_path / "shot.png"
        shot.write_bytes(b"\x89PNG")

        art_id = qa.cmd_baseline_record(
            db_path=db_path, route="/", width=1920, height=1080,
            branch="main", screenshot_path=str(shot),
        )
        capsys.readouterr()
        with pytest.raises(SystemExit):
            qa.cmd_baseline_promote(art_id, db_path=db_path)

    def test_promote_not_found_exits(self, db_path):
        with pytest.raises(SystemExit):
            qa.cmd_baseline_promote(9999, db_path=db_path)
