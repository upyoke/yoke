"""Tests for the done-transition Python engine: post-transition cleanup.

Transition mechanics live in test_done_transition.py.
Gates and CLI tests live in test_done_transition_gates.py.

Pytest fixture (dt_db) shared via _done_transition_test_helpers (private module).
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

from yoke_contracts.api.function_call import FunctionCallResponse
from yoke_core.engines import done_transition
from yoke_core.engines import done_transition_status

pytest_plugins = ("runtime.api.engines._done_transition_test_helpers",)


def _resp(function_id, result=None):
    return FunctionCallResponse(
        success=True, function=function_id, version="v1", result=result or {}
    )


def _insert_item(*args, **kwargs):
    from runtime.api.engines._done_transition_test_helpers import _insert_item as insert

    return insert(*args, **kwargs)


def connect_dt_db(db_path):
    from runtime.api.engines._done_transition_test_helpers import connect_dt_db as connect

    return connect(db_path)


class TestPopulateMergedAt:
    """merged_at is populated when null, preserved when set."""

    def test_populates_when_null(self, dt_db):
        db_path, _ = dt_db
        _insert_item(db_path, 42, merged_at=None, status="implementing")

        done_transition._populate_merged_at(42)

        conn = connect_dt_db(db_path)
        stored = conn.execute("SELECT merged_at FROM items WHERE id = 42").fetchone()[0]
        conn.close()
        assert stored, "merged_at should be populated"
        assert stored.endswith("Z"), f"expected UTC ISO8601, got {stored!r}"

    def test_does_not_overwrite_existing(self, dt_db):
        db_path, _ = dt_db
        original = "2020-01-01T00:00:00Z"
        _insert_item(db_path, 43, merged_at=original, status="implementing")

        done_transition._populate_merged_at(43)

        conn = connect_dt_db(db_path)
        stored = conn.execute("SELECT merged_at FROM items WHERE id = 43").fetchone()[0]
        conn.close()
        assert stored == original, "merged_at must not be overwritten"


class TestCascadeEpicTasksToDone:
    """epic sub-task cascade and auto-promote."""

    def _task_list_stdout(self, *rows: tuple) -> str:
        """Render task-list output in the pipe-delimited format the parser expects."""
        # Columns (parser uses parts[2] task_num, parts[7] status).
        lines = []
        for task_num, status in rows:
            parts = ["epic", "0", str(task_num), "title", "", "", "", status]
            lines.append("|".join(parts))
        return "\n".join(lines) + "\n"

    def test_cascade_non_done_tasks(self, dt_db):
        # The task-list read now relays ``done_transition.epic_task_list``; the
        # cascade/promote writes still go through ``_update_task_status_direct``.
        listing = self._task_list_stdout(
            (1, "implementing"),
            (2, "done"),
            (3, "reviewed-implementation"),
        )
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            if kwargs["function_id"] == "done_transition.epic_task_list":
                return _resp(kwargs["function_id"], {"task_list": listing})
            return _resp(kwargs["function_id"])

        with (
            mock.patch.object(done_transition_status, "call_dispatcher", fake),
            mock.patch.object(
                done_transition, "_update_task_status_direct", return_value=0
            ) as mock_task_direct,
            mock.patch.object(done_transition_status, "_batch_github_sync_tasks"),
        ):
            done_transition._cascade_epic_tasks_to_done(823, item_ref="YOK-823")

        # The task-list relay fires exactly once, for the epic ref.
        task_list_calls = [
            c for c in calls if c["function_id"] == "done_transition.epic_task_list"
        ]
        assert len(task_list_calls) == 1
        # The relay slot carries the internal epic id, not the public ref.
        assert task_list_calls[0]["payload"] == {"epic_id": "823"}

        # Two direct task-status writes — one cascade (task 1), one promote (task 3).
        assert mock_task_direct.call_count == 2
        task_nums = {call.args[1] for call in mock_task_direct.call_args_list}
        assert task_nums == {"1", "3"}
        for call in mock_task_direct.call_args_list:
            # Positional: epic_id, task_num, new_status, note
            assert call.args[0] == 823
            assert call.args[2] == "done"

    def test_cascade_noop_when_no_tasks(self, dt_db):
        calls = []

        def fake(**kwargs):
            calls.append(kwargs)
            return _resp(kwargs["function_id"], {"task_list": ""})

        with (
            mock.patch.object(done_transition_status, "call_dispatcher", fake),
            mock.patch.object(
                done_transition, "_update_task_status_direct"
            ) as mock_task_direct,
        ):
            done_transition._cascade_epic_tasks_to_done(823, item_ref="YOK-823")
        # Only the task-list relay was called — no update writes.
        assert [c["function_id"] for c in calls] == ["done_transition.epic_task_list"]
        mock_task_direct.assert_not_called()


class TestSchemaGate:
    def test_skips_when_no_merge_ran(self, tmp_path, capsys):
        with mock.patch("yoke_core.domain.schema.cmd_init") as schema_init:
            done_transition._schema_gate(merge_ran=False, project_repo=tmp_path)

        schema_init.assert_not_called()
        assert "schema current" in capsys.readouterr().out

    def test_runs_when_schema_files_changed(self, tmp_path):
        conn = mock.MagicMock()
        with (
            mock.patch.object(done_transition, "_run_git") as mock_git,
            mock.patch.object(done_transition, "_connect", return_value=conn),
            mock.patch("yoke_core.domain.schema.cmd_init") as schema_init,
            mock.patch("yoke_core.domain.shepherd.cmd_init") as shepherd_init,
        ):
            mock_git.return_value = mock.Mock(
                returncode=0,
                stdout="runtime/api/domain/schema.py\n",
            )
            done_transition._schema_gate(merge_ran=True, project_repo=tmp_path)

        schema_init.assert_called_once()
        shepherd_init.assert_called_once()
        conn.close()


class TestHandleAlreadyDone:
    """Shell test 14: idempotent re-run on already-done items."""

    def test_handle_already_done_writes_result_and_preserves_status(
        self, dt_db, tmp_path, capsys
    ):
        db_path, _ = dt_db
        _insert_item(db_path, 42, status="done", worktree=None, merged_at=None)

        project_repo = tmp_path / "repo"
        project_repo.mkdir()
        result_file = str(tmp_path / "result.json")
        result = done_transition.TransitionResult(item="YOK-9999")

        with (
            mock.patch.object(done_transition, "_run_git") as mock_git,
            mock.patch.object(done_transition, "_apply_discovery_scan") as scan,
        ):
            mock_git.return_value = mock.Mock(returncode=0, stdout="")
            rc = done_transition._handle_already_done(
                42, project_repo, result, result_file, item_ref="BUZ-7"
            )

        assert rc == 0
        assert "Pre-flight: BUZ-7" in capsys.readouterr().out
        # Status in DB should remain "done" (no status mutation on idempotent re-run)
        conn = connect_dt_db(db_path)
        status = conn.execute("SELECT status FROM items WHERE id = 42").fetchone()[0]
        merged_at = conn.execute(
            "SELECT merged_at FROM items WHERE id = 42"
        ).fetchone()[0]
        conn.close()
        assert status == "done"
        assert merged_at is None
        scan.assert_not_called()
        # Result file was written with already_completed=True
        payload = json.loads(Path(result_file).read_text())
        assert payload["already_completed"] is True
        assert payload["new_status"] == "done"


class TestPushFastPath:
    def test_run_skips_push_when_no_merge_or_commit(self, dt_db):
        db_path, _ = dt_db
        repo_root = db_path.parent
        _insert_item(db_path, 77, status="implemented", worktree="YOK-77")
        git_calls: list[list[str]] = []

        def fake_git(args, **kwargs):
            git_calls.append(args)
            if args[0:3] == ["diff", "--cached", "--quiet"]:
                return mock.Mock(returncode=0, stdout="")
            return mock.Mock(returncode=0, stdout="")

        with _patch_run_internals(
            repo_root,
            _run_git=fake_git,
        ):
            rc = done_transition.run(77)

        assert rc == 0
        assert not any(args[:2] == ["push", "origin"] for args in git_calls)


def _patch_run_internals(repo_root, **overrides):
    """Return an ExitStack context that patches all done_transition internals.

    Shared helper for tests that exercise run() without hitting real git/DB.
    ``overrides`` can replace individual return values or callable side effects
    by function name.
    """
    from contextlib import ExitStack

    stack = ExitStack()
    patches = [
        ("_resolve_repo_root", repo_root),
        ("_resolve_project_context", (repo_root, "")),
        ("_get_base_branch", "main"),
        ("_check_merge_guard", True),
        ("_verify_recovery_evidence", True),
        ("_check_empty_branch", None),
        ("_cleanup_stale_branches", True),
        ("_verify_cwd_after_merge", repo_root),
        ("_schema_gate", None),
        ("_check_deployment_flow_guard", None),
        ("_populate_merged_at", None),
        ("_update_status_to_done", True),
        ("_finalize_done_local_side_effects", None),
        ("_update_item_direct", 0),
        ("_rebuild_board_direct", None),
        ("_run_git", mock.Mock(return_value=mock.Mock(returncode=0, stdout=""))),
    ]
    for attr, default in patches:
        override = overrides.get(attr, default)
        if isinstance(override, mock.Mock):
            stack.enter_context(mock.patch.object(done_transition, attr, override))
        elif callable(override):
            stack.enter_context(
                mock.patch.object(done_transition, attr, side_effect=override)
            )
        else:
            stack.enter_context(
                mock.patch.object(done_transition, attr, return_value=override)
            )
    return stack
