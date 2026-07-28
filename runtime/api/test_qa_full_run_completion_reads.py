"""QA full-schema run completion and read-path tests."""

import pytest

from runtime.api.qa_full_test_helpers import conn_with_rows, make_qa_db_file
from runtime.api.qa_transition_test_support import add_bound_requirement
from yoke_core.domain import qa


@pytest.fixture()
def db_path(tmp_path):
    with make_qa_db_file(tmp_path) as path:
        yield path


def _conn(db_path: str):
    return conn_with_rows(db_path)


class TestRunComplete:
    def test_complete_run(self, db_path, capsys):
        req_id = add_bound_requirement(
            db_path=db_path, item_id=100, qa_kind="smoke", qa_phase="verification"
        )
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            executor_type="pytest",
            qa_kind="smoke",
        )
        capsys.readouterr()
        result = qa.cmd_run_complete(db_path=db_path, run_id=run_id, verdict="pass")
        assert result == run_id
        conn = _conn(db_path)
        row = conn.execute(
            "SELECT verdict, completed_at FROM qa_runs WHERE id=%s", (run_id,)
        ).fetchone()
        conn.close()
        assert row["verdict"] == "pass"
        assert row["completed_at"] is not None

    def test_complete_with_raw_result(self, db_path, capsys):
        req_id = add_bound_requirement(
            db_path=db_path, item_id=100, qa_kind="smoke", qa_phase="verification"
        )
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            executor_type="pytest",
            qa_kind="smoke",
        )
        capsys.readouterr()
        qa.cmd_run_complete(
            db_path=db_path,
            run_id=run_id,
            verdict="fail",
            raw_result="assertion error on line 42",
        )
        conn = _conn(db_path)
        row = conn.execute(
            "SELECT raw_result FROM qa_runs WHERE id=%s", (run_id,)
        ).fetchone()
        conn.close()
        assert "assertion error" in row["raw_result"]

    def test_complete_with_duration(self, db_path, capsys):
        req_id = add_bound_requirement(
            db_path=db_path, item_id=100, qa_kind="smoke", qa_phase="verification"
        )
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            executor_type="pytest",
            qa_kind="smoke",
        )
        capsys.readouterr()
        qa.cmd_run_complete(
            db_path=db_path, run_id=run_id, verdict="pass", duration_ms=1500
        )
        conn = _conn(db_path)
        row = conn.execute(
            "SELECT duration_ms FROM qa_runs WHERE id=%s", (run_id,)
        ).fetchone()
        conn.close()
        assert row["duration_ms"] == 1500

    def test_complete_not_found_exits(self, db_path, capsys):
        capsys.readouterr()
        with pytest.raises(SystemExit):
            qa.cmd_run_complete(db_path=db_path, run_id=9999, verdict="pass")


class TestRunList:
    def test_list_all(self, db_path, capsys):
        req_id = add_bound_requirement(
            db_path=db_path, item_id=100, qa_kind="smoke", qa_phase="verification"
        )
        for verdict in ("pass", "fail"):
            qa.cmd_run_add(
                db_path=db_path,
                requirement_id=req_id,
                executor_type="pytest",
                qa_kind="smoke",
                verdict=verdict,
            )
        capsys.readouterr()
        assert len(qa.cmd_run_list(db_path=db_path)) == 2

    def test_list_by_requirement(self, db_path, capsys):
        r1 = add_bound_requirement(
            db_path=db_path, item_id=100, qa_kind="smoke", qa_phase="verification"
        )
        r2 = add_bound_requirement(
            db_path=db_path, item_id=200, qa_kind="e2e", qa_phase="verification"
        )
        qa.cmd_run_add(
            db_path=db_path,
            requirement_id=r1,
            executor_type="pytest",
            qa_kind="smoke",
            verdict="pass",
        )
        qa.cmd_run_add(
            db_path=db_path,
            requirement_id=r2,
            executor_type="pytest",
            qa_kind="e2e",
            verdict="pass",
        )
        capsys.readouterr()
        assert len(qa.cmd_run_list(db_path=db_path, requirement_id=r1)) == 1

    def test_list_empty(self, db_path, capsys):
        capsys.readouterr()
        assert qa.cmd_run_list(db_path=db_path) == []


class TestRunGet:
    def test_get_existing(self, db_path, capsys):
        req_id = add_bound_requirement(
            db_path=db_path, item_id=100, qa_kind="smoke", qa_phase="verification"
        )
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            executor_type="pytest",
            qa_kind="smoke",
            verdict="pass",
        )
        capsys.readouterr()
        line = qa.cmd_run_get(run_id, db_path=db_path)
        assert str(run_id) in line
        assert "pass" in line

    def test_get_not_found_exits(self, db_path):
        with pytest.raises(SystemExit):
            qa.cmd_run_get(9999, db_path=db_path)
