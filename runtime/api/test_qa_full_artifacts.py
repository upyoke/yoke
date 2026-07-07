"""artifact-add/list — QA artifact insertion and filtered listing.

Covers ``cmd_artifact_add`` (typed handles, with metadata + run
association, bare-path refusal) and ``cmd_artifact_list`` (filtering by
run, by item, with honest handle-address resolution).
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


class TestArtifactAdd:
    """cmd_artifact_add: insert artifacts."""

    def test_add_artifact(self, db_path, capsys):
        art_id = qa.cmd_artifact_add(
            db_path=db_path,
            artifact_type="screenshot",
            content_type="image/png",
            artifact_handle=json.dumps(
                {"backend": "local", "path": "/tmp/shot.png"}
            ),
        )
        assert art_id >= 1

    def test_add_artifact_refuses_bare_path_handle(self, db_path, capsys):
        with pytest.raises(SystemExit):
            qa.cmd_artifact_add(
                db_path=db_path,
                artifact_type="screenshot",
                artifact_handle="/tmp/shot.png",
            )
        err = capsys.readouterr().err
        assert "artifact_handle" in err
        assert "backend" in err

    def test_add_artifact_with_metadata(self, db_path, capsys):
        meta = json.dumps({"route": "/", "viewport": "1920x1080"})
        art_id = qa.cmd_artifact_add(
            db_path=db_path,
            artifact_type="screenshot",
            metadata=meta,
        )
        conn = _conn(db_path)
        row = conn.execute("SELECT metadata FROM qa_artifacts WHERE id=%s", (art_id,)).fetchone()
        conn.close()
        assert json.loads(row[0])["route"] == "/"

    def test_add_artifact_with_run_id(self, db_path, capsys):
        req_id = qa.cmd_requirement_add(
            db_path=db_path, item_id=100, qa_kind="smoke", qa_phase="verification",
        )
        run_id = qa.cmd_run_add(
            db_path=db_path, requirement_id=req_id,
            executor_type="pytest", qa_kind="smoke", verdict="pass",
        )
        capsys.readouterr()
        art_id = qa.cmd_artifact_add(
            db_path=db_path,
            run_id=run_id,
            artifact_type="log",
            content_type="text/plain",
            artifact_handle=json.dumps(
                {"backend": "local", "path": "/tmp/test.log"}
            ),
        )
        conn = _conn(db_path)
        row = conn.execute("SELECT qa_run_id FROM qa_artifacts WHERE id=%s", (art_id,)).fetchone()
        conn.close()
        assert row[0] == run_id


class TestArtifactList:
    """cmd_artifact_list: list artifacts filtered by run."""

    def test_list_all(self, db_path, capsys):
        qa.cmd_artifact_add(db_path=db_path, artifact_type="screenshot")
        qa.cmd_artifact_add(db_path=db_path, artifact_type="log")
        capsys.readouterr()
        lines = qa.cmd_artifact_list(db_path=db_path)
        assert len(lines) == 2

    def test_list_by_run(self, db_path, capsys):
        req_id = qa.cmd_requirement_add(
            db_path=db_path, item_id=100, qa_kind="smoke", qa_phase="verification",
        )
        run_id = qa.cmd_run_add(
            db_path=db_path, requirement_id=req_id,
            executor_type="pytest", qa_kind="smoke", verdict="pass",
        )
        qa.cmd_artifact_add(db_path=db_path, run_id=run_id, artifact_type="screenshot")
        qa.cmd_artifact_add(db_path=db_path, artifact_type="unrelated")
        capsys.readouterr()
        lines = qa.cmd_artifact_list(db_path=db_path, run_id=run_id)
        assert len(lines) == 1

    def test_list_by_item_id(self, db_path, capsys):
        req_id = qa.cmd_requirement_add(
            db_path=db_path, item_id=100, qa_kind="smoke", qa_phase="verification",
        )
        other_req_id = qa.cmd_requirement_add(
            db_path=db_path, item_id=200, qa_kind="smoke", qa_phase="verification",
        )
        run_id = qa.cmd_run_add(
            db_path=db_path, requirement_id=req_id,
            executor_type="pytest", qa_kind="smoke", verdict="pass",
        )
        other_run_id = qa.cmd_run_add(
            db_path=db_path, requirement_id=other_req_id,
            executor_type="pytest", qa_kind="smoke", verdict="pass",
        )
        qa.cmd_artifact_add(
            db_path=db_path, run_id=run_id, artifact_type="screenshot",
            artifact_handle=json.dumps(
                {"backend": "local", "path": "buzz/qa-artifacts/100/1/one.png"}
            ),
        )
        qa.cmd_artifact_add(
            db_path=db_path, run_id=other_run_id, artifact_type="screenshot",
            artifact_handle=json.dumps(
                {"backend": "local", "path": "buzz/qa-artifacts/200/2/two.png"}
            ),
        )
        capsys.readouterr()
        lines = qa.cmd_artifact_list(db_path=db_path, item_id=100)
        assert len(lines) == 1
        assert "one.png" in lines[0]
        assert "two.png" not in lines[0]

    def test_list_by_item_id_resolves_handle_addresses(self, db_path, capsys):
        req_id = qa.cmd_requirement_add(
            db_path=db_path, item_id=100, qa_kind="smoke", qa_phase="verification",
        )
        run_id = qa.cmd_run_add(
            db_path=db_path, requirement_id=req_id,
            executor_type="pytest", qa_kind="smoke", verdict="pass",
        )
        qa.cmd_artifact_add(
            db_path=db_path, run_id=run_id, artifact_type="screenshot",
            artifact_handle=json.dumps({
                "backend": "s3", "bucket": "buzz-prod-artifacts",
                "key": f"qa-artifacts/buzz/100/{run_id}/shot.png",
            }),
        )
        qa.cmd_artifact_add(
            db_path=db_path, run_id=run_id, artifact_type="screenshot",
            artifact_handle=json.dumps(
                {"backend": "local", "path": "/tmp/local-shot.png"}
            ),
        )
        capsys.readouterr()
        lines = qa.cmd_artifact_list(
            db_path=db_path,
            item_id=100,
            resolve_addresses=True,
        )
        assert len(lines) == 2
        # s3 handles address as object URIs; local handles as paths.
        assert (
            f"s3://buzz-prod-artifacts/qa-artifacts/buzz/100/{run_id}/shot.png"
            in lines[0]
        )
        assert "/tmp/local-shot.png" in lines[1]

    def test_list_empty(self, db_path, capsys):
        capsys.readouterr()
        lines = qa.cmd_artifact_list(db_path=db_path)
        assert len(lines) == 0
