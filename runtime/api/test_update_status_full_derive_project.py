"""Pytest behavioral tests for update_status: epic auto-derive and cross-project repo flag."""

from __future__ import annotations

import io
import os
import textwrap

import pytest

import yoke_core.engines.done_transition_runner as done_transition_runner
from yoke_core.domain.update_status_auto_derive import auto_derive_epic_status
from runtime.api.fixtures.file_test_db import connect_test_db
from runtime.api.update_status_full_test_helpers import UpdateStatusEnv


@pytest.fixture
def env(tmp_path):
    e = UpdateStatusEnv(tmp_path, f"test-update-status-{os.getpid()}")
    try:
        yield e
    finally:
        e.close()


class TestAutoDerive:
    """Tests 27, 28, 37, 38 — epic parent status auto-derivation."""

    def _setup_epic_with_tasks(self, env, parent_status="implementing"):
        env.exec_sql(f"""
            DELETE FROM items;
            INSERT INTO items
                (id, title, type, status, priority, project_id, project_sequence,
                 created_at, updated_at)
            VALUES
                (42, 'Test Epic', 'epic', '{parent_status}', 'medium', 1, 42,
                 '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z');
        """)

    def test_all_terminal_derives_reviewing(self, env):
        """TEST 27: all tasks terminal success -> parent reviewing-implementation."""
        self._setup_epic_with_tasks(env)
        env.exec_sql("""
            INSERT INTO epic_tasks
                (epic_id, task_num, title, worktree, status, dispatch_attempts, github_issue)
            VALUES
                (42, 1, 'Task one', 'f/t', 'done', 1, '#100'),
                (42, 2, 'Task two', 'f/t', 'reviewed-implementation', 1, '#101'),
                (42, 3, 'Task three', 'f/t', 'implementing', 1, '#102');
        """)
        env.init_git()
        r = env.run(
            "42", "003", "done",
            extra_env={
                "YOKE_QA_GATE_BYPASS": "1",
                "YOKE_TASK_DONE_VERIFIED": "1",
            },
        )
        assert r.returncode == 0
        assert env.query("SELECT status FROM items WHERE id=42") == "reviewing-implementation"

    def test_in_flight_promotes_planned_parent(self, env):
        """TEST 28: mixed tasks promote planned parent to implementing."""
        self._setup_epic_with_tasks(env, "planned")
        env.exec_sql("""
            INSERT INTO epic_tasks
                (epic_id, task_num, title, worktree, status, dispatch_attempts, github_issue)
            VALUES
                (42, 1, 'Task one', 'f/t', 'done', 1, '#100'),
                (42, 2, 'Task two', 'f/t', 'planned', 0, '#101'),
                (42, 3, 'Task three', 'f/t', 'planned', 0, '#102');
        """)
        env.init_git()
        r = env.run("42", "002", "implementing")
        assert r.returncode == 0
        assert env.query("SELECT status FROM items WHERE id=42") == "implementing"


class TestCrossProject:
    """Tests 31, 32 — cross-project gh calls include -R flag."""

    def _setup_externalwebapp_project(self, env):
        env.exec_sql("""
            INSERT INTO projects (id, slug, name, github_repo)
            VALUES (2, 'externalwebapp', 'ExternalWebapp', 'example-org/externalwebapp')
            ON CONFLICT (id) DO NOTHING;
            INSERT INTO projects (id, slug, name)
            VALUES (1, 'yoke', 'Yoke')
            ON CONFLICT (id) DO NOTHING;
            UPDATE items SET project_id = 2 WHERE id = 42;
        """)

    def test_cross_project_repo_flag(self, env):
        """TEST 31: REST calls target /repos/example-org/externalwebapp/ for externalwebapp items."""
        self._setup_externalwebapp_project(env)
        env.insert_task("planned")
        env.init_git()
        r = env.run("42", "003", "implementing")
        assert r.returncode == 0
        log = env.gh_log.read_text()
        assert "/repos/example-org/externalwebapp/" in log
        # Each side effect (label-create + label-add + comment) targets the
        # externalwebapp repo URL.
        assert "POST /repos/example-org/externalwebapp/labels" in log
        assert "POST /repos/example-org/externalwebapp/issues/100/labels" in log
        assert "POST /repos/example-org/externalwebapp/issues/100/comments" in log

    def test_cross_project_checkbox_repo_flag(self, env):
        """TEST 32: checkbox update on externalwebapp parent uses /repos/example-org/externalwebapp/ URL."""
        import json
        self._setup_externalwebapp_project(env)
        env.exec_sql("""
            UPDATE items
            SET github_issue = '#200',
                project_id = 2,
                status = 'implementing',
                updated_at = '2026-01-01'
            WHERE id = 42;
        """)
        env.insert_task("implementing")
        env.init_git()

        # Seed the parent-issue GET response with the checkbox line.
        rest_dir = env.tmp / "rest-fakes"
        rest_dir.mkdir(exist_ok=True)
        (rest_dir / "GET_repos_example-org_externalwebapp_issues_200.json").write_text(
            json.dumps({
                "status": 200,
                "body": {
                    "number": 200,
                    "body": "- [ ] #100 ExternalWebapp task\n",
                    "state": "open",
                },
            }),
        )

        r = env.run("42", "003", "done", extra_env={"YOKE_TASK_DONE_VERIFIED": "1"})
        assert r.returncode == 0
        log = env.gh_log.read_text()
        # GET parent + PATCH issue both target the externalwebapp repo URL.
        assert "GET /repos/example-org/externalwebapp/issues/200" in log
        # PATCH /issues/100 with state=closed (terminal-status close).
        assert "PATCH /repos/example-org/externalwebapp/issues/100" in log


class TestReleaseFinalize:
    """YOK-1890 — parent epic at ``release`` finalizes via the done-transition
    engine when (and only when) every child task is exactly ``done``.

    These exercise ``auto_derive_epic_status`` in-process with the engine entry
    (``done_transition_runner.run``) replaced by a spy: the auto-derive layer
    owns *detection and routing*; the engine owns the actual ``release -> done``
    write and its claim bypass.  Keeping the engine stubbed isolates the rollup
    decision from the engine's heavy merge/deploy/precondition machinery.
    """

    def _epic_at_release_with_tasks(self, env, task_statuses):
        env.exec_sql("UPDATE items SET status='release' WHERE id=42")
        values = ",\n".join(
            f"(42, {num}, 'Task {num}', 'f/t', '{st}', 1, '#10{num}')"
            for num, st in enumerate(task_statuses, start=1)
        )
        env.exec_sql(
            "INSERT INTO epic_tasks"
            " (epic_id, task_num, title, worktree, status, dispatch_attempts, github_issue)"
            f" VALUES {values};"
        )

    def _spy_engine(self, monkeypatch, *, returns=0):
        calls = []

        def _spy(item_id, **kwargs):
            calls.append((item_id, kwargs))
            return returns

        monkeypatch.setattr(done_transition_runner, "run", _spy)
        return calls

    def test_all_children_done_invokes_engine(self, env, monkeypatch):
        """AC-1/AC-4/AC-8: all children exactly done + parent release routes
        through the engine; auto-derive performs no direct status='done' write."""
        monkeypatch.delenv("YOKE_CLAIM_BYPASS", raising=False)
        self._epic_at_release_with_tasks(env, ["done", "done", "done"])
        calls = self._spy_engine(monkeypatch)

        conn = connect_test_db(str(env.db_path))
        out, err = io.StringIO(), io.StringIO()
        try:
            auto_derive_epic_status(conn, "42", "done", stdout=out, stderr=err)
        finally:
            conn.close()

        assert len(calls) == 1
        assert calls[0][0] == 42  # bare int epic id
        # The engine (stubbed) owns the write — auto-derive left status alone.
        assert env.query("SELECT status FROM items WHERE id=42") == "release"
        assert "release -> done" in out.getvalue()

    def test_non_done_child_does_not_finalize(self, env, monkeypatch):
        """AC-2: a non-done child blocks finalization and is named in output."""
        monkeypatch.delenv("YOKE_CLAIM_BYPASS", raising=False)
        self._epic_at_release_with_tasks(env, ["done", "done", "blocked"])
        calls = self._spy_engine(monkeypatch)

        conn = connect_test_db(str(env.db_path))
        out, err = io.StringIO(), io.StringIO()
        try:
            auto_derive_epic_status(conn, "42", "blocked", stdout=out, stderr=err)
        finally:
            conn.close()

        assert calls == []
        assert env.query("SELECT status FROM items WHERE id=42") == "release"
        text = out.getvalue()
        assert "not auto-finalizing" in text
        assert "task 3=blocked" in text

    def test_done_cascade_bypass_does_not_finalize(self, env, monkeypatch):
        """AC-3: task writes under a ``done-cascade:`` bypass never ping-pong
        into an upward finalize attempt, even with all children done."""
        monkeypatch.setenv("YOKE_CLAIM_BYPASS", "done-cascade:YOK-42")
        self._epic_at_release_with_tasks(env, ["done", "done", "done"])
        calls = self._spy_engine(monkeypatch)

        conn = connect_test_db(str(env.db_path))
        out, err = io.StringIO(), io.StringIO()
        try:
            auto_derive_epic_status(conn, "42", "done", stdout=out, stderr=err)
        finally:
            conn.close()

        assert calls == []
        assert env.query("SELECT status FROM items WHERE id=42") == "release"

    def test_engine_refusal_leaves_parent_at_release(self, env, monkeypatch):
        """Failure/recovery: when the engine refuses, the parent stays at
        release and the refusal is surfaced for the operator."""
        monkeypatch.delenv("YOKE_CLAIM_BYPASS", raising=False)
        self._epic_at_release_with_tasks(env, ["done", "done", "done"])
        calls = self._spy_engine(monkeypatch, returns=7)

        conn = connect_test_db(str(env.db_path))
        out, err = io.StringIO(), io.StringIO()
        try:
            auto_derive_epic_status(conn, "42", "done", stdout=out, stderr=err)
        finally:
            conn.close()

        assert len(calls) == 1
        assert env.query("SELECT status FROM items WHERE id=42") == "release"
        assert "refused" in err.getvalue()
        assert "exit 7" in err.getvalue()
