"""Tests for the done-transition engine: sys.path[0] re-anchoring +
loaded-package ``__path__`` reseat against worktree deletion.

The TestSysPathReanchor class verifies that done_transition correctly
re-anchors sys.path[0] to repo_root after os.chdir, even when the
startup CWD has been deleted (e.g., a worktree that no longer exists).

The TestPackagePathReseat class verifies the companion fix: when a
``runtime.*`` package was loaded from the launching directory and that
directory is deleted mid-run, subsequent lazy submodule imports must
resolve from ``repo_root`` instead of the cached deleted entry. The
runner's Step 1 calls ``_reseat_runtime_paths`` to update each loaded
package's cached ``__path__`` accordingly.

Pytest fixture (dt_db) shared via _done_transition_test_helpers (private module).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from unittest import mock

from yoke_core.engines import done_transition

from yoke_core.engines._done_transition_test_helpers import (
    _insert_item,
    dt_db,
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
        ("_cleanup_stale_branches", None),
        ("_verify_cwd_after_merge", repo_root),
        ("_schema_gate", None),
        ("_check_deployment_flow_guard", None),
        ("_cross_project_commit_guard", None),
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
        """AC-1 / AC-3: sys.path[0] is corrected even when startup path
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
        """AC-5: the late status-update step runs after sys.path[0] has
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


class TestPackagePathReseat:
    """Loaded-package ``__path__`` cached entries must be reseated after a
    worktree-delete-mid-run so subsequent lazy submodule imports succeed.

    Uses a synthetic package prefix (``_synthpkg``) so the test never
    mutates real ``runtime.*`` packages — touching real ``runtime.*``
    __path__ entries inside the live test process would break sibling
    tests.
    """

    def _build_parallel_trees(self, tmp_path, *, pkg_name):
        import os

        launched_from = tmp_path / "launched"
        repo_root = tmp_path / "main"
        for base, marker in (
            (launched_from, "from-launched"),
            (repo_root, "from-main"),
        ):
            pkg = base / pkg_name
            os.makedirs(str(pkg), exist_ok=False)
            (pkg / "__init__.py").write_text("")
            (pkg / "sub.py").write_text(
                f"VALUE = {marker!r}\n",
            )
        return launched_from, repo_root

    def test_reseat_repoints_loaded_package_to_repo_root(self, tmp_path):
        """AC-6 / AC-7: a package loaded from launched_from has its
        cached __path__ reseated to point under repo_root after the
        helper runs, and the deleted launched_from no longer matters."""
        import shutil
        from yoke_core.engines.done_transition_runtime import (
            _reseat_package_paths,
        )

        pkg_name = "_synthpkg_reseat_a"
        launched_from, repo_root = self._build_parallel_trees(
            tmp_path, pkg_name=pkg_name,
        )

        sys.path.insert(0, str(launched_from))
        try:
            mod = __import__(pkg_name)
            cached_path_before = list(mod.__path__)
            assert cached_path_before[0] == str(launched_from / pkg_name)

            shutil.rmtree(str(launched_from))

            reseated = _reseat_package_paths(
                launched_from, repo_root, package_prefix=pkg_name,
            )
            assert pkg_name in reseated

            cached_path_after = list(sys.modules[pkg_name].__path__)
            assert cached_path_after[0] == str(
                (repo_root / pkg_name).resolve()
            )
        finally:
            sys.path.remove(str(launched_from))
            for name in list(sys.modules):
                if name == pkg_name or name.startswith(pkg_name + "."):
                    sys.modules.pop(name, None)

    def test_lazy_submodule_import_succeeds_after_worktree_delete(
        self, tmp_path,
    ):
        """AC-7: the regression scenario — package loaded from worktree,
        worktree deleted, lazy submodule import resolves from main
        checkout because __path__ was reseated. The submodule import
        consults the package's cached __path__, not sys.path, so once
        the helper reseats __path__ no further sys.path manipulation
        is needed."""
        import shutil
        from yoke_core.engines.done_transition_runtime import (
            _reseat_package_paths,
        )

        pkg_name = "_synthpkg_reseat_b"
        launched_from, repo_root = self._build_parallel_trees(
            tmp_path, pkg_name=pkg_name,
        )

        sys.path.insert(0, str(launched_from))
        try:
            __import__(pkg_name)  # sticky-load from launched_from
            assert pkg_name in sys.modules
            mod = sys.modules[pkg_name]
            # Verify the cached __path__ actually came from launched_from
            # (otherwise the test is meaningless).
            assert any(
                str(launched_from) in p for p in list(mod.__path__)
            )

            shutil.rmtree(str(launched_from))
            _reseat_package_paths(
                launched_from, repo_root, package_prefix=pkg_name,
            )

            # Lazy import the submodule — this would raise ImportError
            # before the fix because the package's cached __path__ still
            # pointed at the deleted directory.
            sub = __import__(pkg_name + ".sub", fromlist=["sub"])
            assert sub.VALUE == "from-main"
        finally:
            try:
                sys.path.remove(str(launched_from))
            except ValueError:
                pass
            for name in list(sys.modules):
                if name == pkg_name or name.startswith(pkg_name + "."):
                    sys.modules.pop(name, None)

    def test_reseat_is_noop_when_launched_equals_repo_root(self, tmp_path):
        """No work needed when invoked from the main checkout."""
        from yoke_core.engines.done_transition_runtime import (
            _reseat_package_paths,
        )

        pkg_name = "_synthpkg_reseat_c"
        # Single tree — launched_from == repo_root.
        (tmp_path / pkg_name).mkdir()
        (tmp_path / pkg_name / "__init__.py").write_text("")

        sys.path.insert(0, str(tmp_path))
        try:
            __import__(pkg_name)
            reseated = _reseat_package_paths(
                tmp_path, tmp_path, package_prefix=pkg_name,
            )
            assert reseated == []
        finally:
            sys.path.remove(str(tmp_path))
            sys.modules.pop(pkg_name, None)
