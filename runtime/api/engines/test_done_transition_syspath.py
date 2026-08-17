"""The done-transition engine must re-anchor ``sys.path[0]``.

When done_transition is invoked from a worktree CWD, Python sets
``sys.path[0]`` to the worktree. After the worktree is deleted, lazy imports
that search ``sys.path[0]`` would crash, so the runner re-anchors it to
``repo_root``. The companion defense — repointing packages already loaded out
of that worktree — is covered with its own module in
``runtime/api/domain/test_worktree_import_reseat.py``.

Pytest fixture (dt_db) shared via _done_transition_test_helpers (private module).
"""

from __future__ import annotations

import sys
from unittest import mock

from yoke_core.engines import done_transition

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
        ("_sync_done_item_direct", None),
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

