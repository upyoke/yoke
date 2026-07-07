"""init + requirement-add/list/get/waive — schema bootstrap and requirement CRUD.

Covers ``cmd_init`` idempotency and the requirement lifecycle: insertion under
each attachment target (item, epic-task, deployment-run), filtering, retrieval,
and the waiver flow with its blocking-mode guard.
"""

from __future__ import annotations

import json

import pytest

from yoke_core.domain import qa
from yoke_core.domain.schema_common import _table_exists
from runtime.api.qa_full_test_helpers import conn_with_rows, make_qa_db_file


@pytest.fixture()
def db_path(tmp_path):
    with make_qa_db_file(tmp_path) as path:
        yield path


def _conn(db_path: str):
    return conn_with_rows(db_path)


class TestInit:
    """cmd_init idempotency."""

    def test_init_creates_tables(self, db_path):
        conn = _conn(db_path)
        try:
            assert _table_exists(conn, "qa_requirements")
            assert _table_exists(conn, "qa_runs")
            assert _table_exists(conn, "qa_artifacts")
        finally:
            conn.close()

    def test_init_idempotent(self, db_path):
        qa.cmd_init(db_path=db_path)  # should not raise


class TestRequirementAdd:
    """cmd_requirement_add: insert with various attachment targets."""

    def test_add_item_requirement(self, db_path, capsys):
        req_id = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=100,
            qa_kind="smoke",
            qa_phase="verification",
        )
        assert req_id >= 1
        captured = capsys.readouterr()
        assert str(req_id) in captured.out

    def test_add_epic_task_requirement(self, db_path, capsys):
        req_id = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=None,
            epic_id=50,
            task_num=1,
            qa_kind="integration",
            qa_phase="verification",
        )
        assert req_id >= 1

    def test_add_deployment_run_requirement(self, db_path, capsys):
        req_id = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=None,
            deployment_run_id="run-test-001",
            qa_kind="e2e",
            qa_phase="post_deploy",
        )
        assert req_id >= 1

    def test_add_no_target_exits(self, db_path):
        with pytest.raises(SystemExit):
            qa.cmd_requirement_add(
                db_path=db_path,
                item_id=None,
                qa_kind="smoke",
                qa_phase="verification",
            )

    def test_add_multiple_targets_exits(self, db_path):
        with pytest.raises(SystemExit):
            qa.cmd_requirement_add(
                db_path=db_path,
                item_id=100,
                epic_id=50,
                task_num=1,
                qa_kind="smoke",
                qa_phase="verification",
            )

    def test_add_epic_without_task_num_exits(self, db_path):
        with pytest.raises(SystemExit):
            qa.cmd_requirement_add(
                db_path=db_path,
                item_id=None,
                epic_id=50,
                qa_kind="smoke",
                qa_phase="verification",
            )

    def test_add_with_blocking_mode(self, db_path, capsys):
        req_id = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=100,
            qa_kind="e2e",
            qa_phase="verification",
            blocking_mode="non_blocking",
        )
        conn = _conn(db_path)
        row = conn.execute("SELECT blocking_mode FROM qa_requirements WHERE id=%s", (req_id,)).fetchone()
        conn.close()
        assert row[0] == "non_blocking"

    def test_add_with_success_policy(self, db_path, capsys):
        policy = json.dumps({"threshold": 0.95})
        req_id = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=100,
            qa_kind="smoke",
            qa_phase="verification",
            success_policy=policy,
        )
        conn = _conn(db_path)
        row = conn.execute("SELECT success_policy FROM qa_requirements WHERE id=%s", (req_id,)).fetchone()
        conn.close()
        assert json.loads(row[0])["threshold"] == 0.95

    def test_add_browser_smoke_requires_success_policy(self, db_path):
        """Browser QA kinds must have success_policy with steps array."""
        with pytest.raises(SystemExit):
            qa.cmd_requirement_add(
                db_path=db_path,
                item_id=100,
                qa_kind="browser_smoke",
                qa_phase="verification",
            )

    def test_add_browser_smoke_valid_policy(self, db_path, capsys):
        policy = json.dumps({
            "steps": [
                {"action": "navigate", "route": "/"},
                {"action": "screenshot", "capture": True},
            ]
        })
        req_id = qa.cmd_requirement_add(
            db_path=db_path,
            item_id=100,
            qa_kind="browser_smoke",
            qa_phase="verification",
            success_policy=policy,
        )
        assert req_id >= 1

    def test_add_browser_smoke_missing_action(self, db_path):
        """Steps without 'action' field are rejected."""
        policy = json.dumps({"steps": [{"route": "/"}]})
        with pytest.raises(SystemExit):
            qa.cmd_requirement_add(
                db_path=db_path,
                item_id=100,
                qa_kind="browser_smoke",
                qa_phase="verification",
                success_policy=policy,
            )


class TestRequirementList:
    """cmd_requirement_list: filter by attachment target."""

    def test_list_by_item(self, db_path, capsys):
        qa.cmd_requirement_add(db_path=db_path, item_id=100, qa_kind="smoke", qa_phase="verification")
        qa.cmd_requirement_add(db_path=db_path, item_id=100, qa_kind="e2e", qa_phase="verification")
        qa.cmd_requirement_add(db_path=db_path, item_id=200, qa_kind="smoke", qa_phase="verification")

        capsys.readouterr()  # clear previous output
        lines = qa.cmd_requirement_list(db_path=db_path, item_id=100)
        assert len(lines) == 2

    def test_list_by_epic(self, db_path, capsys):
        qa.cmd_requirement_add(
            db_path=db_path, item_id=None, epic_id=50, task_num=1,
            qa_kind="smoke", qa_phase="verification",
        )
        capsys.readouterr()
        lines = qa.cmd_requirement_list(db_path=db_path, epic_id=50)
        assert len(lines) == 1

    def test_list_all(self, db_path, capsys):
        qa.cmd_requirement_add(db_path=db_path, item_id=100, qa_kind="smoke", qa_phase="verification")
        qa.cmd_requirement_add(db_path=db_path, item_id=200, qa_kind="smoke", qa_phase="verification")
        capsys.readouterr()
        lines = qa.cmd_requirement_list(db_path=db_path)
        assert len(lines) == 2

    def test_list_empty(self, db_path, capsys):
        capsys.readouterr()
        lines = qa.cmd_requirement_list(db_path=db_path, item_id=999)
        assert len(lines) == 0


class TestRequirementGet:
    """cmd_requirement_get: retrieve single requirement."""

    def test_get_existing(self, db_path, capsys):
        req_id = qa.cmd_requirement_add(
            db_path=db_path, item_id=100, qa_kind="smoke", qa_phase="verification",
        )
        capsys.readouterr()
        line = qa.cmd_requirement_get(req_id, db_path=db_path)
        assert str(req_id) in line
        assert "smoke" in line

    def test_get_not_found_exits(self, db_path):
        with pytest.raises(SystemExit):
            qa.cmd_requirement_get(9999, db_path=db_path)


class TestRequirementWaive:
    """cmd_requirement_waive: waiver with blocking mode guard."""

    def test_waive_non_blocking(self, db_path, capsys):
        req_id = qa.cmd_requirement_add(
            db_path=db_path, item_id=100, qa_kind="smoke",
            qa_phase="verification", blocking_mode="non_blocking",
        )
        capsys.readouterr()
        qa.cmd_requirement_waive(req_id, "Not needed", db_path=db_path)
        captured = capsys.readouterr()
        assert "Waived" in captured.out

    def test_waive_blocking_without_force_exits(self, db_path, capsys):
        req_id = qa.cmd_requirement_add(
            db_path=db_path, item_id=100, qa_kind="smoke",
            qa_phase="verification", blocking_mode="blocking",
        )
        capsys.readouterr()
        with pytest.raises(SystemExit):
            qa.cmd_requirement_waive(req_id, "Override", db_path=db_path)

    def test_waive_blocking_with_force(self, db_path, capsys):
        req_id = qa.cmd_requirement_add(
            db_path=db_path, item_id=100, qa_kind="smoke",
            qa_phase="verification", blocking_mode="blocking",
        )
        capsys.readouterr()
        qa.cmd_requirement_waive(req_id, "Override", db_path=db_path, force=True)
        captured = capsys.readouterr()
        assert "Waived" in captured.out

    def test_waive_records_source(self, db_path, capsys):
        req_id = qa.cmd_requirement_add(
            db_path=db_path, item_id=100, qa_kind="smoke",
            qa_phase="verification", blocking_mode="non_blocking",
        )
        capsys.readouterr()
        qa.cmd_requirement_waive(req_id, "Operator decision", db_path=db_path, source="operator")
        conn = _conn(db_path)
        row = conn.execute("SELECT waiver_source, waiver_rationale FROM qa_requirements WHERE id=%s", (req_id,)).fetchone()
        conn.close()
        assert row["waiver_source"] == "operator"
        assert row["waiver_rationale"] == "Operator decision"

    def test_waive_not_found_exits(self, db_path):
        with pytest.raises(SystemExit):
            qa.cmd_requirement_waive(9999, "test", db_path=db_path)
