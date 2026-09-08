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
from runtime.api.qa_transition_test_support import add_bound_requirement


@pytest.fixture()
def db_path(tmp_path):
    with make_qa_db_file(tmp_path) as path:
        yield path


def _conn(db_path: str):
    return conn_with_rows(db_path)


class TestArtifactAdd:
    """cmd_artifact_add: insert artifacts."""

    def test_add_artifact_without_run_cannot_ingest_local_handle(self, db_path, capsys):
        with pytest.raises(SystemExit):
            qa.cmd_artifact_add(
                db_path=db_path,
                artifact_type="screenshot",
                content_type="image/png",
                artifact_handle=json.dumps(
                    {"backend": "local", "path": "/tmp/shot.png"}
                ),
            )
        assert "requires a QA run owner" in capsys.readouterr().err

    def test_add_artifact(self, db_path, capsys):
        art_id = qa.cmd_artifact_add(
            db_path=db_path,
            artifact_type="screenshot",
            content_type="image/png",
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
        row = conn.execute(
            "SELECT metadata FROM qa_artifacts WHERE id=%s", (art_id,)
        ).fetchone()
        conn.close()
        assert json.loads(row[0])["route"] == "/"

    def test_add_artifact_with_run_id(self, db_path, capsys, tmp_path, monkeypatch):
        req_id = add_bound_requirement(
            db_path=db_path,
            item_id=100,
            qa_kind="smoke",
            qa_phase="verification",
        )
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            performed_by="pytest",
            qa_kind="smoke",
            verdict="pass",
        )
        capsys.readouterr()
        source = tmp_path / "test.log"
        source.write_text("evidence", encoding="utf-8")
        monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
        monkeypatch.setattr(
            "yoke_core.domain.handlers.qa_artifact_presign.resolve_artifacts_bucket",
            lambda *_args: None,
        )
        art_id = qa.cmd_artifact_add(
            db_path=db_path,
            run_id=run_id,
            artifact_type="log",
            content_type="text/plain",
            artifact_handle=json.dumps({"backend": "local", "path": str(source)}),
        )
        conn = _conn(db_path)
        row = conn.execute(
            "SELECT qa_run_id FROM qa_artifacts WHERE id=%s", (art_id,)
        ).fetchone()
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
        req_id = add_bound_requirement(
            db_path=db_path,
            item_id=100,
            qa_kind="smoke",
            qa_phase="verification",
        )
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            performed_by="pytest",
            qa_kind="smoke",
            verdict="pass",
        )
        qa.cmd_artifact_add(db_path=db_path, run_id=run_id, artifact_type="screenshot")
        qa.cmd_artifact_add(db_path=db_path, artifact_type="unrelated")
        capsys.readouterr()
        lines = qa.cmd_artifact_list(db_path=db_path, run_id=run_id)
        assert len(lines) == 1

    def test_list_by_item_id(self, db_path, capsys, tmp_path, monkeypatch):
        req_id = add_bound_requirement(
            db_path=db_path,
            item_id=100,
            qa_kind="smoke",
            qa_phase="verification",
        )
        other_req_id = add_bound_requirement(
            db_path=db_path,
            item_id=200,
            qa_kind="smoke",
            qa_phase="verification",
        )
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            performed_by="pytest",
            qa_kind="smoke",
            verdict="pass",
        )
        other_run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=other_req_id,
            performed_by="pytest",
            qa_kind="smoke",
            verdict="pass",
        )
        monkeypatch.setenv("YOKE_MACHINE_HOME", str(tmp_path / "machine"))
        monkeypatch.setattr(
            "yoke_core.domain.handlers.qa_artifact_presign.resolve_artifacts_bucket",
            lambda *_args: None,
        )
        one = tmp_path / "one.png"
        two = tmp_path / "two.png"
        one.write_bytes(b"one")
        two.write_bytes(b"two")
        qa.cmd_artifact_add(
            db_path=db_path,
            run_id=run_id,
            artifact_type="screenshot",
            artifact_handle=json.dumps(
                {
                    "backend": "local",
                    "path": str(one),
                }
            ),
        )
        qa.cmd_artifact_add(
            db_path=db_path,
            run_id=other_run_id,
            artifact_type="screenshot",
            artifact_handle=json.dumps(
                {
                    "backend": "local",
                    "path": str(two),
                }
            ),
        )
        capsys.readouterr()
        lines = qa.cmd_artifact_list(db_path=db_path, item_id=100)
        assert len(lines) == 1
        assert "one.png" in lines[0]
        assert "two.png" not in lines[0]

    def test_list_by_item_id_resolves_handle_addresses(
        self, db_path, capsys, tmp_path
    ):
        req_id = add_bound_requirement(
            db_path=db_path,
            item_id=100,
            qa_kind="smoke",
            qa_phase="verification",
        )
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            performed_by="pytest",
            qa_kind="smoke",
            verdict="pass",
        )
        local = tmp_path / "local-shot.png"
        local.write_bytes(b"shot")
        conn = _conn(db_path)
        conn.execute(
            "INSERT INTO qa_artifacts "
            "(qa_run_id,artifact_type,artifact_handle,created_at) "
            "VALUES (%s,'screenshot',%s,'2026-01-01T00:00:00Z'),"
            "(%s,'screenshot',%s,'2026-01-01T00:00:00Z')",
            (
                run_id,
                json.dumps({
                    "backend": "s3",
                    "bucket": "externalwebapp-prod-artifacts",
                    "key": f"qa-artifacts/externalwebapp/100/{run_id}/shot.png",
                }),
                run_id,
                json.dumps({"backend": "local", "path": str(local)}),
            ),
        )
        conn.commit()
        conn.close()
        capsys.readouterr()
        lines = qa.cmd_artifact_list(
            db_path=db_path,
            item_id=100,
            resolve_addresses=True,
        )
        assert len(lines) == 2
        # s3 handles address as object URIs; local handles as paths.
        assert (
            f"s3://externalwebapp-prod-artifacts/qa-artifacts/externalwebapp/100/{run_id}/shot.png"
            in lines[0]
        )
        assert str(local) in lines[1]

    def test_list_empty(self, db_path, capsys):
        capsys.readouterr()
        lines = qa.cmd_artifact_list(db_path=db_path)
        assert len(lines) == 0
