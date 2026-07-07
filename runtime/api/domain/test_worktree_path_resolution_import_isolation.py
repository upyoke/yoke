"""Regression coverage for the DB-path resolver / worktree-facade
import-isolation contract.

The contract under test:

* ``db_helpers.resolve_db_path()`` refuses retired SQLite authority under
  Postgres without importing the heavy siblings.
* The ``python3 -m yoke_core.domain.worktree paths db`` diagnostic CLI
  refuses the physical retired DB path without importing
  :mod:`yoke_core.domain.worktree_create`,
  :mod:`yoke_core.domain.worktree_deps`, or
  :mod:`yoke_core.domain.worktree_item_resolve`.
* When one of those heavy siblings is broken (simulated by pre-injecting a
  poisoned module into ``sys.modules``), both path-only surfaces preserve the
  same outcome.

These tests use subprocess invocations with ``-c`` scripts so that
Python's module cache starts fresh for every case — pre-loaded test
state in the parent process cannot mask a regression.

The companion subprocess-driver helper lives in this module
(``_run_in_subprocess``) so the contract is self-contained.
"""

from __future__ import annotations

import os
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[3]


HEAVY_SIBLINGS = (
    "yoke_core.domain.worktree_create",
    "yoke_core.domain.worktree_deps",
    "yoke_core.domain.worktree_item_resolve",
)


def _run_in_subprocess(script: str) -> subprocess.CompletedProcess:
    """Run ``script`` in a fresh Python subprocess rooted at this repo."""
    env = {**os.environ}
    # Ensure subprocess can import runtime.* — sys.path[0] becomes the
    # repo root when we pass ``-c`` from this cwd.
    env["PYTHONPATH"] = (
        f"{REPO_ROOT}{os.pathsep}{env.get('PYTHONPATH', '')}".rstrip(os.pathsep)
    )
    return subprocess.run(
        [sys.executable, "-c", textwrap.dedent(script)],
        env=env,
        cwd=str(REPO_ROOT),
        capture_output=True,
        text=True,
    )


class TestPathOnlyImportIsolation:
    """Importing the worktree facade for path-only use must not pull in
    the heavy provisioning siblings."""

    def test_resolve_db_path_does_not_import_worktree_create(self) -> None:
        script = """
            import sys
            from yoke_core.domain import db_helpers
            try:
                db_helpers.resolve_db_path()
            except RuntimeError as exc:
                assert 'SQLite authority retired/guarded' in str(exc), exc
            else:
                raise AssertionError('resolve_db_path unexpectedly returned')
            heavy = [m for m in (
                'yoke_core.domain.worktree_create',
                'yoke_core.domain.worktree_deps',
                'yoke_core.domain.worktree_item_resolve',
            ) if m in sys.modules]
            if heavy:
                print('FAIL: ' + ','.join(heavy))
                sys.exit(1)
            print('OK')
        """
        result = _run_in_subprocess(script)
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout

    def test_paths_db_cli_refuses_without_importing_worktree_create(self) -> None:
        script = """
            import sys
            sys.argv = ['worktree', 'paths', 'db']
            from yoke_core.domain import worktree as wt
            rc = wt.main()
            heavy = [m for m in (
                'yoke_core.domain.worktree_create',
                'yoke_core.domain.worktree_deps',
                'yoke_core.domain.worktree_item_resolve',
            ) if m in sys.modules]
            if heavy:
                print('FAIL: ' + ','.join(heavy))
                sys.exit(1)
            sys.exit(rc)
        """
        result = _run_in_subprocess(script)
        assert result.returncode == 1, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "SQLite authority retired/guarded" in result.stderr


class TestPathOnlyResolverSurvivesBrokenSibling:
    """Pre-injecting a broken heavy sibling into ``sys.modules`` must
    NOT break the path-only resolver path."""

    @pytest.mark.parametrize("broken_sibling", HEAVY_SIBLINGS)
    def test_resolve_db_path_survives_broken_sibling(
        self, broken_sibling: str,
    ) -> None:
        script = f"""
            import sys
            import types
            broken = types.ModuleType({broken_sibling!r})

            def _raise(*a, **kw):
                raise ImportError('simulated break for isolation test')

            # Populate plausible attributes so any consumer that touches
            # the broken module gets a real-looking failure rather than
            # an AttributeError that masks the contract.
            broken.create_worktree = _raise
            broken.CreateWorktreeResult = None
            broken.install_worktree_deps = _raise
            broken.detect_deps = _raise
            broken.resolve_playwright_cache = _raise
            broken.resolve_item_worktree = _raise
            broken.ResolvedWorktree = None
            sys.modules[{broken_sibling!r}] = broken

            from yoke_core.domain import db_helpers
            try:
                db_helpers.resolve_db_path()
            except RuntimeError as exc:
                assert 'SQLite authority retired/guarded' in str(exc), exc
                print('OK')
            else:
                raise AssertionError('resolve_db_path unexpectedly returned')
        """
        result = _run_in_subprocess(script)
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout

    @pytest.mark.parametrize("broken_sibling", HEAVY_SIBLINGS)
    def test_paths_db_cli_survives_broken_sibling(
        self, broken_sibling: str,
    ) -> None:
        script = f"""
            import sys
            import types
            broken = types.ModuleType({broken_sibling!r})

            def _raise(*a, **kw):
                raise ImportError('simulated break for isolation test')

            broken.create_worktree = _raise
            broken.CreateWorktreeResult = None
            broken.install_worktree_deps = _raise
            broken.detect_deps = _raise
            broken.resolve_playwright_cache = _raise
            broken.resolve_item_worktree = _raise
            broken.ResolvedWorktree = None
            sys.modules[{broken_sibling!r}] = broken

            sys.argv = ['worktree', 'paths', 'db']
            from yoke_core.domain import worktree as wt
            rc = wt.main()
            sys.exit(rc)
        """
        result = _run_in_subprocess(script)
        assert result.returncode == 1, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "SQLite authority retired/guarded" in result.stderr


class TestWorktreeFacadeLazyContract:
    """The lazy-attribute contract on
    :mod:`yoke_core.domain.worktree`: heavy names are resolvable via
    PEP 562 ``__getattr__`` without being eagerly imported at module
    import time."""

    def test_lazy_attribute_resolves_create_worktree(self) -> None:
        script = """
            import sys
            from yoke_core.domain import worktree as wt
            # Heavy sibling must NOT be loaded just by importing wt.
            assert 'yoke_core.domain.worktree_create' not in sys.modules, (
                list(sys.modules.keys())
            )
            # Touching the attribute triggers the lazy import.
            create_fn = wt.create_worktree  # noqa: F841
            assert 'yoke_core.domain.worktree_create' in sys.modules
            print('OK')
        """
        result = _run_in_subprocess(script)
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout

    def test_unknown_attribute_still_raises_attribute_error(self) -> None:
        script = """
            from yoke_core.domain import worktree as wt
            try:
                wt.this_attribute_definitely_does_not_exist
            except AttributeError as exc:
                assert 'this_attribute_definitely_does_not_exist' in str(exc)
                print('OK')
        """
        result = _run_in_subprocess(script)
        assert result.returncode == 0, (
            f"stdout={result.stdout!r} stderr={result.stderr!r}"
        )
        assert "OK" in result.stdout
