"""The done-transition engine must re-anchor ``sys.path[0]``.

When done_transition is invoked from a worktree CWD, Python sets
``sys.path[0]`` to the worktree. After the worktree is deleted, lazy imports
that search ``sys.path[0]`` would crash, so the runner re-anchors it to
``repo_root``. The companion defense — repointing packages already loaded out
of that worktree — is covered with its own module in
``runtime/api/domain/test_worktree_import_reseat.py``.

Re-anchoring is only half the defense, because a lane carries the
interpreter and the installed packages too — neither of which a corrected
``sys.path[0]`` can bring back. ``TestLanePrunedLast`` covers the other
half: the lane is deleted only after every step that still reads it.

Pytest fixture (dt_db) shared via _done_transition_test_helpers (private module).
"""

from __future__ import annotations

import shutil
import sys
from unittest import mock

from yoke_core.engines import (
    done_transition,
    done_transition_finalize,
    done_transition_github_sync,
)
from yoke_core.engines.done_transition_result import TransitionResult

from runtime.api.engines._done_transition_test_helpers import (
    _insert_item,
)


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


class TestSysPathReanchor:
    """sys.path[0] must be corrected after os.chdir(repo_root).

    When done_transition is invoked from a worktree CWD, Python sets
    sys.path[0] to the worktree.  After the worktree is deleted, lazy
    imports that search sys.path[0] would crash.  The fix re-anchors
    sys.path[0] to repo_root in step 1.
    """

    def test_syspath0_set_to_repo_root_after_step1(self, dt_db):
        """Sys.path[0] is corrected even when startup path
        is a non-existent directory (simulating deleted worktree)."""
        db_path, repo_root = dt_db
        _insert_item(db_path, 99, status="implemented")

        fake_startup_path = str(repo_root / "deleted-worktree")
        original_syspath0 = sys.path[0]

        try:
            sys.path[0] = fake_startup_path
            with _patch_run_internals(repo_root):
                done_transition.run(99)
            # After run() completes, sys.path[0] must be repo_root,
            # not the fake startup path.
            assert sys.path[0] == str(repo_root)
        finally:
            sys.path[0] = original_syspath0

    def test_status_update_step_sees_reanchored_syspath0(self, dt_db):
        """The late status-update step runs after sys.path[0] has
        already been re-anchored to repo_root."""
        db_path, repo_root = dt_db
        _insert_item(db_path, 100, status="implemented")

        fake_startup_path = str(repo_root / "nonexistent-worktree")
        original_syspath0 = sys.path[0]
        observed = {}

        def record_syspath0(*_args, **_kwargs):
            observed["value"] = sys.path[0]
            return True

        try:
            sys.path[0] = fake_startup_path
            with _patch_run_internals(
                repo_root,
                _update_status_to_done=record_syspath0,
            ):
                rc = done_transition.run(100)
            assert rc == 0
            assert observed["value"] == str(repo_root)
        finally:
            sys.path[0] = original_syspath0



def _finish(result, *, prune_lane, apply_step_8, tmp_path):
    """Drive the closeout with git, board, and route reporting stubbed out."""
    engine = mock.MagicMock()
    engine._run_git.return_value = mock.Mock(returncode=0)  # nothing staged
    with mock.patch.object(
        done_transition_github_sync, "apply_step_8", apply_step_8
    ), mock.patch.object(
        done_transition_finalize, "format_workflow_route", lambda _w: ""
    ):
        return done_transition_finalize.finish_done_transition(
            engine,
            result,
            result_file=str(tmp_path / "result.json"),
            item_id=99,
            title="title",
            old_status="implemented",
            workflow=None,
            repo_root=str(tmp_path),
            merge_ran=False,
            item_ref="YOK-99",
            prune_lane=prune_lane,
        )


class TestLanePrunedLast:
    """Terminal cleanup must not delete the tree the process still reads.

    Pruning immediately after the status write left the GitHub done-sync
    resolving its import against a directory that had just been removed:
    the transition had landed, and the run still exited 1 with a traceback.
    """

    def test_github_sync_runs_while_the_lane_is_still_on_disk(self, tmp_path):
        lane = tmp_path / "lane"
        lane.mkdir()
        result = TransitionResult()
        seen = {}

        def _sync(_item_id, _old_status, run_result, *, item_ref):
            seen["lane_present_at_sync"] = lane.is_dir()
            run_result.add_step("8")

        def _prune():
            seen["sync_ran_first"] = "8" in result.steps_completed
            shutil.rmtree(lane)

        exit_code = _finish(
            result, prune_lane=_prune, apply_step_8=_sync, tmp_path=tmp_path,
        )

        assert seen["lane_present_at_sync"] is True
        assert seen["sync_ran_first"] is True
        assert not lane.exists()
        assert exit_code == 0
        assert "4a" in result.steps_completed

    def test_a_failed_closeout_keeps_the_landed_transition_successful(
        self, tmp_path, capsys,
    ):
        """A closeout that cannot finish is reported, not turned into failure.

        The status write and any merge are already committed by this point,
        so a non-zero exit invites a rollback that would desync the item
        from git.
        """
        result = TransitionResult()
        result.add_step("6")
        pruned = []

        def _sync(*_args, **_kwargs):
            raise ModuleNotFoundError("No module named 'anything'")

        exit_code = _finish(
            result,
            prune_lane=lambda: pruned.append(True),
            apply_step_8=_sync,
            tmp_path=tmp_path,
        )

        assert exit_code == 0
        assert result.warnings[-1]["kind"] == "closeout_incomplete"
        assert result.warnings[-1]["after_step"] == "6"
        assert pruned == [], "an unfinished closeout must leave the lane alone"
        err = capsys.readouterr().err
        assert "Closeout incomplete" in err
        assert "do not roll the item back" in err
