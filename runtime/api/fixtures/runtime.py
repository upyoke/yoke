"""Runtime fixtures: filesystem pollution detection, event isolation, and CWD guard.

Session-scoped and function-scoped autouse fixtures that protect the test
suite from leaking state into the canonical filesystem or event ledger.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import pytest

# ---------------------------------------------------------------------------
# Filesystem-pollution detection
# ---------------------------------------------------------------------------

# Known state-dir and residue patterns to watch for at the repo root.
_POLLUTION_PATTERNS = {
    "yoke",  # pre-migration state dir
}

# Files that indicate DB residue under a non-state directory.
_DB_RESIDUE_FILES = {
    "yoke.db",
    "yoke.db-shm",
    "yoke.db-wal",
    "yoke.db-journal",
}


def _resolve_test_repo_root() -> Optional[Path]:
    """Resolve the repo root for pollution checking.

    Returns None if we can't determine the repo root (e.g. running in CI
    with no git context).
    """
    try:
        # Walk up from this file to find the repo root
        # fixtures/ -> api/ -> runtime/ -> repo root
        candidate = Path(__file__).resolve().parent.parent.parent.parent
        if (candidate / ".git").exists():
            return candidate
    except Exception:
        pass
    return None


def _snapshot_worktree_dirs(repo_root: Path) -> set[str]:
    """Return the set of `YOK-*` entry names under ``<repo>/.worktrees/``."""
    worktrees_dir = repo_root / ".worktrees"
    if not worktrees_dir.is_dir():
        return set()
    return {
        entry.name for entry in worktrees_dir.iterdir()
        if entry.name.startswith("YOK-")
    }


def _capture_pollution_baseline(repo_root: Path) -> dict:
    """Snapshot the pre-suite filesystem surfaces the pollution check watches."""
    runtime_dir = repo_root / "runtime"
    return {
        "repo_root": repo_root,
        "runtime_dir": runtime_dir,
        "pre_dirs": {d.name for d in repo_root.iterdir() if d.is_dir()},
        "pre_runtime_db_files": (
            {
                f.name for f in runtime_dir.iterdir()
                if f.is_file() and f.name in _DB_RESIDUE_FILES
            }
            if runtime_dir.is_dir()
            else set()
        ),
        "pre_worktree_entries": _snapshot_worktree_dirs(repo_root),
    }


def _check_pollution_against_baseline(baseline: dict) -> None:
    """Compare current state to ``baseline`` and ``pytest.fail`` on new pollution."""
    repo_root: Path = baseline["repo_root"]
    runtime_dir: Path = baseline["runtime_dir"]
    created_pollution: list[str] = []
    leaked_worktree_entries: list[str] = []
    try:
        post_dirs = {d.name for d in repo_root.iterdir() if d.is_dir()}
        for d in post_dirs - baseline["pre_dirs"]:
            if d in _POLLUTION_PATTERNS:
                created_pollution.append(str(repo_root / d))

        if runtime_dir.is_dir():
            post_runtime_db_files = {
                f.name for f in runtime_dir.iterdir()
                if f.is_file() and f.name in _DB_RESIDUE_FILES
            }
            for f in post_runtime_db_files - baseline["pre_runtime_db_files"]:
                created_pollution.append(str(runtime_dir / f))

        post_worktree_entries = _snapshot_worktree_dirs(repo_root)
        for name in sorted(post_worktree_entries - baseline["pre_worktree_entries"]):
            leaked_worktree_entries.append(str(repo_root / ".worktrees" / name))
    except Exception:
        return

    if not (created_pollution or leaked_worktree_entries):
        return

    sections: list[str] = []
    if created_pollution:
        sibling = "\n  ".join(created_pollution)
        sections.append(
            "Stray sibling-state residue:\n  "
            f"{sibling}\n"
            "This indicates a write-path guard regression. "
            "See yoke_core.domain.schema.guard_state_dir_creation."
        )
    if leaked_worktree_entries:
        wt = "\n  ".join(leaked_worktree_entries)
        sections.append(
            "Leaked .worktrees/YOK-* directories:\n  "
            f"{wt}\n"
            "A test drove the unified worktree creator (or its preflight) "
            "against the real repo. Rule: tests must not leak "
            ".worktrees/YOK-* into the canonical checkout. "
            "Fix the test by patching every reachable import of "
            "`create_worktree` (both `worktree_cli.create_worktree` "
            "and the direct `yoke_core.domain.worktree_create` "
            "import in `worktree_preflight`), or scope `repo_root` "
            "to a tempdir."
        )
    pytest.fail(
        "Filesystem pollution detected:\n\n" + "\n\n".join(sections),
        pytrace=False,
    )


@pytest.fixture(autouse=True, scope="session")
def _yoke_filesystem_pollution_check():
    """Detect stray sibling-state directories, DB residue, and `.worktrees/YOK-*` leaks.

    Snapshots three surfaces before the suite runs and asserts no new
    entries appear after it completes:

    Known state-dir and residue patterns to watch for:
      - Sibling state dirs at the repo root (legacy `yoke/` pre-migration dir).
      - DB residue files (`yoke.db`, `yoke.db-wal`, etc.) under `runtime/`.
      - `.worktrees/YOK-*` directories: a test path that drives the unified
        worktree creator (or its preflight) without monkeypatching every
        import surface can land a real git worktree against the canonical
        repo. The snapshot/diff fails the suite if new `YOK-*` entries appear
        post-run.

    The body delegates to :func:`_capture_pollution_baseline` and
    :func:`_check_pollution_against_baseline` so regression tests can
    exercise the same check without violating pytest's "fixtures are not
    called directly" rule.
    """
    repo_root = _resolve_test_repo_root()
    if repo_root is None:
        yield
        return
    baseline = _capture_pollution_baseline(repo_root)
    yield
    _check_pollution_against_baseline(baseline)


# ---------------------------------------------------------------------------
# Canonical-ledger write isolation
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _yoke_event_isolation(monkeypatch):
    """Enable ``YOKE_EVENTS_ISOLATION=1`` for every Yoke API test.

    Function-scoped so ``monkeypatch`` cleans it up after each test -- this
    also means tests that explicitly want to disable isolation can call
    ``monkeypatch.delenv("YOKE_EVENTS_ISOLATION", raising=False)`` in
    their own setup without fighting the fixture.
    """
    monkeypatch.setenv("YOKE_EVENTS_ISOLATION", "1")
    yield


# ---------------------------------------------------------------------------
# CWD restoration guard
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _yoke_cwd_guard():
    """Restore CWD after each test to prevent cross-test contamination.

    Tests that call code which does ``os.chdir()`` (e.g.
    ``done_transition.run()``) can leave the process CWD pointing at a
    temp directory.  Later tests that shell out to ``git rev-parse
    --show-toplevel`` then fail because the CWD is not in a git repo.
    """
    cwd = os.getcwd()
    yield
    if os.getcwd() != cwd:
        os.chdir(cwd)
