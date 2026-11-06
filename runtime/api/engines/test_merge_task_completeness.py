# ruff: noqa: F811
"""Merge completeness uses the workflow-owned task-success set."""

from runtime.api.engines._merge_worktree_test_helpers import mw_db  # noqa: F401, F811


class TestPreflightEpicTasks:
    def test_all_tasks_complete(self, mw_db):
        conn = mw_db["conn"]
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, status) VALUES ('100', 1, 'done')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, status) VALUES ('100', 2, 'reviewed-implementation')"
        )
        conn.commit()

        # Direct DB check matching preflight logic
        from yoke_core.domain.workflow_runtime import builtin_workflow_runtime

        terminal_list = ",".join(
            "'" + value + "'"
            for value in sorted(
                builtin_workflow_runtime("epic").successful_task_stage_ids
            )
        )
        incomplete = conn.execute(
            f"SELECT task_num, status FROM epic_tasks "
            f"WHERE epic_id='100' AND status NOT IN ({terminal_list}) "
            f"ORDER BY task_num"
        ).fetchall()
        assert len(incomplete) == 0

    def test_incomplete_tasks(self, mw_db):
        conn = mw_db["conn"]
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, status) VALUES ('100', 1, 'done')"
        )
        conn.execute(
            "INSERT INTO epic_tasks (epic_id, task_num, status) VALUES ('100', 2, 'implementing')"
        )
        conn.commit()

        from yoke_core.domain.workflow_runtime import builtin_workflow_runtime

        terminal_list = ",".join(
            "'" + value + "'"
            for value in sorted(
                builtin_workflow_runtime("epic").successful_task_stage_ids
            )
        )
        incomplete = conn.execute(
            f"SELECT task_num, status FROM epic_tasks "
            f"WHERE epic_id='100' AND status NOT IN ({terminal_list}) "
            f"ORDER BY task_num"
        ).fetchall()
        assert len(incomplete) == 1
        assert incomplete[0][0] == 2


def test_missing_workflow_metadata_blocks_task_merge(monkeypatch):
    from types import SimpleNamespace
    from yoke_core.engines import merge_task_completeness as checks

    response = SimpleNamespace(success=True, result={"tasks": []})
    monkeypatch.setattr(checks, "call_dispatcher", lambda **kwargs: response)
    refusal = checks.task_completion_failure(f"ACM-{1}")
    assert "workflow_status_metadata_unavailable" in refusal
    assert "serving floor" in refusal


def test_task_merge_uses_the_returned_workflow_handoff(monkeypatch):
    from types import SimpleNamespace
    from yoke_core.engines import merge_task_completeness as checks

    result = {
        "tasks": [{"task_num": 1, "status": "verified"}],
        "successful_task_stage_ids": ["verified", "archived"],
    }
    monkeypatch.setattr(
        checks,
        "call_dispatcher",
        lambda **kwargs: SimpleNamespace(success=True, result=result),
    )
    assert checks.task_completion_failure(f"ACM-{1}") is None
    result["tasks"][0]["status"] = "done"
    assert "task_completion_incomplete" in checks.task_completion_failure(f"ACM-{1}")
