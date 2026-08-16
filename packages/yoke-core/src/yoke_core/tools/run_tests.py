"""Yoke test runner.

Entry point for running the Yoke Python test suite. Delegates to pytest
with Yoke-specific defaults (project-registered test paths, sensible
output, optional fast/slow filtering) so that:

1. Agents and skills have one canonical command to call:
   ``python3 -m yoke_core.tools.run_tests``.
2. Future changes to test layout, markers, or plugins are absorbed here
   instead of scattered across every caller.

Usage::

    python3 -m yoke_core.tools.run_tests                     # run everything (parallel by default)
    python3 -m yoke_core.tools.run_tests runtime/api/test_items_query.py
    python3 -m yoke_core.tools.run_tests -k dependency       # keyword filter
    python3 -m yoke_core.tools.run_tests --fail-fast         # stop at first failure
    python3 -m yoke_core.tools.run_tests --quiet              # minimal output
    python3 -m yoke_core.tools.run_tests --list               # collect-only, list nodes
    python3 -m yoke_core.tools.run_tests --no-parallel        # serial mode (debug order)

Parallel-by-default: ``-n auto`` (pytest-xdist) is injected unless the
caller passes ``--no-parallel`` or supplies its own ``-n``/
``--numprocesses`` after ``--``.

The runner refuses to execute outside the calling session's claim-bound
worktree (see :mod:`yoke_core.domain.verification_tree_binding`), because
a run rooted in the wrong tree reports a green for code nobody changed.
Pass ``--allow-tree-mismatch`` for a deliberate cross-tree run.

Return codes match pytest (0 = all pass, nonzero = failures/errors).
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from typing import List, Sequence, TextIO

from yoke_core.domain import process_group_reaping
from yoke_core.domain import verification_tree_binding
from yoke_core.domain import verification_tree_binding_pytest_startup as _tree_binding_startup
from yoke_core.tools._pytest_parallel import (
    apply_parallel_default,
    apply_postgres_xdist_auto_env,
)
from yoke_core.tools import _source_pythonpath
from yoke_core.tools.impacted_project_test_roots import (
    UNSUPPORTED_PROJECT_TEST_ROOTS,
    default_testpaths,
)
from yoke_core.tools.watch_pytest_project_python import pytest_argv


DEFAULT_TESTPATHS: tuple[str, ...] = ("runtime/api", "runtime/harness", "tests")

#: Surface name carried by this runner's tree-binding refusal.
_TREE_BINDING_SURFACE = "run_tests"

#: Shell convention for "died on signal N" (130 = Ctrl-C, 143 = SIGTERM).
_EXIT_STATUS_SIGNAL_BASE = 128

#: Exit code for a run refused before pytest started, matching the
#: watcher wrapper so callers branch on one value for either entry point.
_EXIT_STATUS_TREE_BINDING_REFUSED = (
    _tree_binding_startup.TREE_BINDING_REFUSED_EXIT_STATUS
)


def _repo_root(start: Path | None = None) -> Path:
    """Walk up from *start* to find the repo root (marked by pyproject.toml).

    The default starting point is the current working directory — not
    ``__file__`` — so that callers invoking the runner from a different repo
    (for example, a test case pointing at a mini-repo) have their CWD honored
    rather than silently redirected to the Yoke package's own checkout.
    """
    here = (start or Path.cwd()).resolve()
    for candidate in [here, *here.parents]:
        if (candidate / "pyproject.toml").exists():
            return candidate
    # Fall back to CWD — the runner can still be invoked outside the repo.
    return Path.cwd()


def build_pytest_argv(
    paths: Sequence[str],
    *,
    keyword: str | None = None,
    fail_fast: bool = False,
    quiet: bool = False,
    list_only: bool = False,
    no_parallel: bool = False,
    extra: Sequence[str] = (),
) -> List[str]:
    """Build the argv passed to ``pytest``."""
    argv: List[str] = []

    if list_only:
        # --collect-only prints test nodes without running them. Pair with -q
        # so the output is one-node-per-line for downstream tooling.
        argv.extend(["--collect-only", "-q"])
    elif quiet:
        argv.append("-q")
    else:
        # Default: show short test progress with a summary of failures.
        argv.append("-ra")

    if fail_fast:
        argv.append("-x")

    if keyword:
        argv.extend(["-k", keyword])

    argv.extend(extra)
    argv.extend(paths or DEFAULT_TESTPATHS)

    # Collect-only is non-executing; xdist would error trying to dispatch
    # workers for a discovery pass, so skip the parallel default there.
    if not list_only:
        argv = apply_parallel_default(argv, no_parallel=no_parallel)
    return argv


def _is_yoke_backend_verification(root: Path, paths: Sequence[str]) -> bool:
    """Return true when the runner is about to execute Yoke's API suite."""
    if not (root / "runtime" / "api").is_dir():
        return False
    candidate_paths = list(paths or DEFAULT_TESTPATHS)
    return any(
        path == "runtime/api" or path.startswith("runtime/api/")
        for path in candidate_paths
    )


def _prepare_yoke_backend_env(root: Path, stderr: TextIO = sys.stderr) -> bool:
    """Verify Postgres authority before launching Yoke's API tests.

    Returning false lets the runner fail before pytest starts, with a
    diagnostic tied to the worktree/repo root rather than a late backend
    resolution failure from inside the test suite.
    """
    try:
        from yoke_core.domain import db_backend

        db_backend.resolve_pg_dsn()
        return True
    except Exception as exc:
        print(
            "Error: Postgres authority setup failed before pytest started. "
            f"Worktree/repo root: {root}. "
            "Recovery: set YOKE_PG_DSN, YOKE_PG_DSN_FILE, or a usable "
            "connected-env binding. "
            f"Detail: {exc}",
            file=stderr,
        )
        return False


def run(
    paths: Sequence[str] | None = None,
    *,
    keyword: str | None = None,
    fail_fast: bool = False,
    quiet: bool = False,
    list_only: bool = False,
    no_parallel: bool = False,
    extra: Sequence[str] = (),
    repo_root: Path | None = None,
    allow_tree_mismatch: bool = False,
) -> int:
    """Invoke pytest with the computed argv.

    Returns the pytest exit code, or
    ``_EXIT_STATUS_TREE_BINDING_REFUSED`` when the resolved root is
    outside the calling session's claimed worktree. The runner never
    raises on test failure; callers should check the return code.
    """
    root = (repo_root or _repo_root()).resolve()

    binding = verification_tree_binding.evaluate_run(
        surface=_TREE_BINDING_SURFACE,
        tree=str(root),
        allow_mismatch=allow_tree_mismatch,
    )
    if binding.notice is not None:
        print(binding.notice, file=sys.stderr)
    if binding.refusal is not None:
        print(binding.refusal, file=sys.stderr)
        return _EXIT_STATUS_TREE_BINDING_REFUSED

    requested = list(paths or default_testpaths(root) or ())
    if not requested:
        if _source_pythonpath.is_yoke_shaped_tree(root):
            requested = list(DEFAULT_TESTPATHS)
        else:
            print(f"run_tests {UNSUPPORTED_PROJECT_TEST_ROOTS}", file=sys.stderr)
            return 1

    if _is_yoke_backend_verification(root, requested):
        if not _prepare_yoke_backend_env(root):
            return 1

    argv = build_pytest_argv(
        requested,
        keyword=keyword,
        fail_fast=fail_fast,
        quiet=quiet,
        list_only=list_only,
        no_parallel=no_parallel,
        extra=extra,
    )
    cmd = pytest_argv(argv, cwd=root)
    env = os.environ.copy()
    # Ensure pytest imports Yoke packages from this checkout, even when an
    # editable install still points at the main tree.
    env = _source_pythonpath.with_source_pythonpath(env, root)
    env = apply_postgres_xdist_auto_env(argv, env)
    # Already judged above; the child's startup check inherits that answer.
    env = _tree_binding_startup.with_binding_evaluated(env)
    if (root / "packages" / "yoke-core" / "src" / "yoke_core").is_dir():
        refusal = _source_pythonpath.import_origin_refusal(root, env=env)
        if refusal is not None:
            print(f"Error: {refusal}", file=sys.stderr)
            return 1

    import contextlib

    from yoke_core.tools import gate_admission

    # Collection-only runs are cheap on every axis and never take a slot.
    admission = (
        contextlib.nullcontext()
        if list_only
        else gate_admission.admitted_gate(list(paths or ()))
    )
    with admission:
        # Own the process group so an interrupted run takes its xdist workers
        # down with it. Workers that outlive the runner keep their test
        # databases open, and the next run then blocks on databases nobody is
        # using.
        proc = process_group_reaping.popen_in_process_group(
            cmd, cwd=str(root), env=gate_admission.admitted_environment(env)
        )
        try:
            with process_group_reaping.interruption_reaps_process_group(proc):
                return proc.wait()
        except process_group_reaping.ProcessGroupInterrupted as interruption:
            return _EXIT_STATUS_SIGNAL_BASE + interruption.signal_number


def _parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="yoke-run-tests",
        description="Run Yoke's Python test suite.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help=(
            "Optional test paths (defaults to "
            f"{' '.join(DEFAULT_TESTPATHS)})."
        ),
    )
    parser.add_argument(
        "-k",
        "--keyword",
        default=None,
        help="pytest -k expression to filter tests by substring/keyword.",
    )
    parser.add_argument(
        "--fail-fast",
        "-x",
        action="store_true",
        help="Stop at first failing test (pytest -x).",
    )
    parser.add_argument(
        "--quiet",
        "-q",
        action="store_true",
        help="Minimal output (pytest -q).",
    )
    parser.add_argument(
        "--list",
        dest="list_only",
        action="store_true",
        help="Collect and list test node IDs without running (pytest --collect-only).",
    )
    parser.add_argument(
        "--no-parallel",
        dest="no_parallel",
        action="store_true",
        help=(
            "Disable pytest-xdist parallel execution (default is "
            "``-n auto``). Use to debug order-sensitive failures."
        ),
    )
    parser.add_argument(
        verification_tree_binding.ALLOW_TREE_MISMATCH_FLAG,
        dest="allow_tree_mismatch",
        action="store_true",
        help=(
            "Run even when the resolved repo root is outside the session's "
            "claimed worktree. For a deliberate cross-tree run; the runner "
            "names both trees so the result is attributable."
        ),
    )
    parser.add_argument(
        "--",
        dest="passthrough_separator",
        nargs=argparse.REMAINDER,
        help=argparse.SUPPRESS,
    )
    return parser.parse_args(list(argv))


def main(argv: Sequence[str] | None = None) -> int:
    """CLI entry point."""
    raw = list(sys.argv[1:] if argv is None else argv)

    # argparse's REMAINDER with -- is fiddly; do a manual split so anything
    # after ``--`` is passed verbatim to pytest.
    passthrough: List[str] = []
    if "--" in raw:
        idx = raw.index("--")
        passthrough = raw[idx + 1 :]
        raw = raw[:idx]

    ns = _parse_args(raw)
    return run(
        ns.paths,
        keyword=ns.keyword,
        fail_fast=ns.fail_fast,
        quiet=ns.quiet,
        list_only=ns.list_only,
        no_parallel=ns.no_parallel,
        extra=passthrough,
        allow_tree_mismatch=ns.allow_tree_mismatch,
    )


if __name__ == "__main__":  # pragma: no cover — exercised via subprocess
    sys.exit(main())
