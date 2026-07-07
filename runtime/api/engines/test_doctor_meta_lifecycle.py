"""Doctor meta-HCs covering epic-task worktrees, body, dependency, and flow.

Registry/quality/integrity/flow HCs live in test_doctor_meta.py.
Project FK/JSON/ephemeral/lifecycle HCs live in test_doctor_meta_project.py.

Schema scaffolding is shared via _doctor_meta_test_helpers (private module).
"""

from __future__ import annotations

from yoke_core.engines._doctor_meta_test_helpers import (
    _args,
    _make_conn,
    _results,
)
from yoke_core.engines.doctor import (
    RecordCollector,
    hc_dependency_drift,
    hc_empty_task_worktree,
    hc_epic_task_worktree,
    hc_missing_flow,
    hc_orphan_epic_tasks,
    hc_shepherd_spec_integrity,
    hc_stale_body,
)


class TestEpicTaskWorktree:
    def test_pass_all_have_worktree(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (1, 'Epic', 'epic', 'implementing')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (id, epic_id, task_num, title, worktree, status) "
            "VALUES (1, 1, 1, 'Task', 'YOK-1', 'implementing')"
        )
        rec = RecordCollector()
        hc_epic_task_worktree(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-epic-task-worktree"][0] == "PASS"

    def test_warn_null_worktree(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (1, 'Epic', 'epic', 'implementing')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (id, epic_id, task_num, title, worktree, status) "
            "VALUES (1, 1, 1, 'Task', NULL, 'implementing')"
        )
        rec = RecordCollector()
        hc_epic_task_worktree(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-epic-task-worktree"][0] == "WARN"


class TestEmptyTaskWorktree:
    def test_pass_when_no_active_tasks(self):
        conn = _make_conn()
        rec = RecordCollector()
        hc_empty_task_worktree(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-empty-task-worktree"][0] == "PASS"


class TestOrphanEpicTasks:
    def test_pass_all_have_parent(self):
        conn = _make_conn()
        conn.execute("INSERT INTO items (id, title) VALUES (1, 'Epic')")
        conn.execute(
            "INSERT INTO epic_tasks (id, epic_id, task_num, title) "
            "VALUES (1, 1, 1, 'Task')"
        )
        rec = RecordCollector()
        hc_orphan_epic_tasks(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-orphan-epic-tasks"][0] == "PASS"

    def test_warn_orphan_task(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO epic_tasks (id, epic_id, task_num, title) "
            "VALUES (1, 999, 1, 'Orphan task')"
        )
        rec = RecordCollector()
        hc_orphan_epic_tasks(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-orphan-epic-tasks"][0] == "WARN"


class TestStaleBody:
    def test_pass_spec_updated_at_present(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, spec_updated_at) "
            "VALUES (1, 'Test', 'idea', '2026-01-02T00:00:00Z')"
        )
        rec = RecordCollector()
        hc_stale_body(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-stale-body"][0] == "PASS"

    def test_pass_no_spec_updated_at(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status) "
            "VALUES (1, 'Test', 'idea')"
        )
        rec = RecordCollector()
        hc_stale_body(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-stale-body"][0] == "PASS"


class TestShepherdSpecIntegrity:
    def test_pass_epic_with_spec(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status, spec) "
            "VALUES (1, 'Epic', 'epic', 'implementing', 'Some spec content')"
        )
        rec = RecordCollector()
        hc_shepherd_spec_integrity(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-shepherd-spec-integrity"][0] == "PASS"

    def test_warn_epic_without_spec(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, type, status) "
            "VALUES (1, 'Epic', 'epic', 'implementing')"
        )
        rec = RecordCollector()
        hc_shepherd_spec_integrity(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-shepherd-spec-integrity"][0] == "WARN"


class TestDependencyDrift:
    def test_pass_no_depends_on_column(self):
        """When depends_on column doesn't exist, should PASS."""
        conn = _make_conn()
        rec = RecordCollector()
        hc_dependency_drift(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-dependency-drift"][0] == "PASS"


class TestMissingFlow:
    def test_pass_all_items_have_flow(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, deployment_flow) "
            "VALUES (1, 'Test', 'implementing', 'flow-1')"
        )
        rec = RecordCollector()
        hc_missing_flow(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-missing-flow"][0] == "PASS"

    def test_warn_missing_flow(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, deployment_flow) "
            "VALUES (1, 'Test', 'implementing', NULL)"
        )
        rec = RecordCollector()
        hc_missing_flow(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-missing-flow"][0] == "WARN"

    def test_warn_idea_missing_flow(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, deployment_flow) "
            "VALUES (1, 'Test', 'idea', NULL)"
        )
        rec = RecordCollector()
        hc_missing_flow(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-missing-flow"][0] == "WARN"

    def test_pass_wontdo_missing_flow(self):
        conn = _make_conn()
        conn.execute(
            "INSERT INTO items (id, title, status, deployment_flow) "
            "VALUES (1, 'Test', 'wontdo', NULL)"
        )
        rec = RecordCollector()
        hc_missing_flow(conn, _args(), rec)
        res = _results(rec)
        assert res["HC-missing-flow"][0] == "PASS"
