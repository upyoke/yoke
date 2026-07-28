"""QA run completion and read-path tests."""

from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.qa_test_helpers import make_basic_requirement, make_qa_db_file
from runtime.api.qa_transition_test_support import add_bound_requirement
from yoke_core.domain import qa


@pytest.fixture()
def db_path(tmp_path: Path):
    with make_qa_db_file(tmp_path) as path:
        yield path


@pytest.fixture()
def req_id(db_path: str) -> int:
    return make_basic_requirement(db_path)


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
        row = conn.execute(
            "SELECT verdict, completed_at FROM qa_runs WHERE id = %s", (run_id,)
        ).fetchone()
        conn.close()
        assert row[0] == "pass"
        assert row[1] is not None

    def test_complete_with_optional_fields(self, db_path: str, req_id: int) -> None:
        run_id = qa.cmd_run_add(
            db_path=db_path,
            requirement_id=req_id,
            executor_type="agent",
            qa_kind="unit_test",
        )
        qa.cmd_run_complete(
            db_path=db_path,
            run_id=run_id,
            verdict="fail",
            raw_result="test X failed",
            duration_ms=500,
        )
        conn = connect_test_db(db_path)
        row = conn.execute(
            "SELECT verdict, raw_result, duration_ms FROM qa_runs WHERE id = %s",
            (run_id,),
        ).fetchone()
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
        qa.cmd_run_add(db_path=db_path, requirement_id=req_id, executor_type="a")
        qa.cmd_run_add(db_path=db_path, requirement_id=req_id, executor_type="b")
        assert len(qa.cmd_run_list(db_path=db_path)) == 2

    def test_run_list_filter(self, db_path: str, req_id: int) -> None:
        qa.cmd_run_add(db_path=db_path, requirement_id=req_id, executor_type="a")
        second_id = add_bound_requirement(
            db_path=db_path, item_id=99, qa_kind="z", qa_phase="verification"
        )
        qa.cmd_run_add(db_path=db_path, requirement_id=second_id, executor_type="b")
        assert len(qa.cmd_run_list(db_path=db_path, requirement_id=req_id)) == 1

    def test_run_get(self, db_path: str, req_id: int) -> None:
        run_id = qa.cmd_run_add(
            db_path=db_path, requirement_id=req_id, executor_type="a"
        )
        assert qa.cmd_run_get(run_id, db_path=db_path).startswith(str(run_id))

    def test_run_get_missing_exits(self, db_path: str) -> None:
        with pytest.raises(SystemExit) as exc:
            qa.cmd_run_get(9999, db_path=db_path)
        assert exc.value.code == 1
