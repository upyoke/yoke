"""Shared infrastructure for merge-worktree tests.

Subprocess-based black-box tests for ``python3 -m yoke_core.engines.merge_worktree``.
Test classes live in sibling modules; this module owns the fixture, helpers,
dataclasses, mock gh scripts, and DB helpers used by those suites.

Run the full suite via:
    pytest test_merge_worktree_prepare.py \
           test_merge_worktree_execute.py \
           test_merge_worktree_post.py
"""

import os
import stat
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pytest

# Mock gh scripts and DB helpers live in support modules to keep this file small,
# and are surfaced here as the shared fixture API for merge-worktree suites.
from runtime.api.merge_worktree_test_mocks import (
    MOCK_GH_DIRTY_SCRIPT,
    MOCK_GH_NO_CHECKS_REPORTED,
    MOCK_GH_PR_CREATE_EMPTY_URL,
    MOCK_GH_PR_CREATE_HARD_FAIL,
    MOCK_GH_PR_EXISTS_REUSE,
    MOCK_GH_PR_EXISTS_UNRESOLVABLE,
    MOCK_GH_PR_MERGE_FAIL,
    MOCK_GH_SCRIPT,
    MOCK_GH_TARGET_MOVED_DURING_CI,
)
from runtime.api.merge_worktree_test_db import (
    _create_epic_tasks_db,
    _insert_canonical_integration_simulation,
    _insert_plain_text_integration_simulation,
)
from runtime.api.source_pythonpath_test_helpers import (
    REPO_ROOT as WORKTREE_ROOT,
    SOURCE_PYTHONPATH,
)


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
SCRIPTS_DIR = WORKTREE_ROOT / ".agents" / "skills" / "yoke" / "scripts"
MERGE_MODULE = "yoke_core.engines.merge_worktree"
TEST_ITEM_ID = 42
TEST_BRANCH = f"YOK-{TEST_ITEM_ID}"
TEST_GIT_TIMEOUT_SECONDS = "15"


# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------
@dataclass
class MergeEnv:
    """All paths and env needed to run the merge-worktree engine in a test."""

    tmpdir: Path
    repo: Path  # main repo (clone of origin)
    worktree: Path  # worktree for TEST_BRANCH
    origin: Path  # bare origin repo
    mock_dir: Path  # directory containing mock gh
    gh_log: Path  # log file for mock gh invocations
    yoke_root: Path  # state dir containing yoke.db
    db_path: Path  # path to test yoke.db
    test_path: str  # PATH with mock gh first, then scripts dir
    rest_fake_dir: Path  # directory containing REST canned responses

    def env(
        self,
        *,
        done_transition: bool = True,
        extra: Optional[dict] = None,
    ) -> dict:
        """Build environment dict for subprocess calls."""
        e = {
            "PATH": self.test_path,
            "MOCK_GH_LOG": str(self.gh_log),
            "MOCK_GH_ORIGIN": str(self.origin),
            "YOKE_DB": str(self.db_path),
            "YOKE_ROOT": str(self.yoke_root),
            "YOKE_REST_FAKE_DIR": str(self.rest_fake_dir),
            "YOKE_EVENTS_REGISTRY_VALIDATE": "0",
            "HOME": os.environ.get("HOME", "/tmp"),
            "TMPDIR": os.environ.get("TMPDIR", "/tmp"),
            # git needs these
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GIT_SSH_COMMAND": "ssh -oBatchMode=yes",
            "YOKE_GIT_COMMAND_TIMEOUT_SECONDS": TEST_GIT_TIMEOUT_SECONDS,
        }
        # YOKE_MACHINE_HOME must ride along: HOME passes through for
        # git, and without the per-test machine home the subprocess
        # resolves the OPERATOR's live ~/.yoke config — on an
        # https-default machine its board.data.get dispatch relays to
        # live prod instead of in-process (the 12349 hermeticity class,
        # subprocess edition).
        for key in ("YOKE_PG_DSN", "YOKE_PG_DSN_FILE",
                    "YOKE_MACHINE_HOME"):
            if key in os.environ:
                e[key] = os.environ[key]
        if done_transition:
            e["YOKE_DONE_TRANSITION"] = "1"
        if extra:
            e.update(extra)
        return e


@dataclass
class MergeResult:
    """Captured output from a merge-worktree engine run."""

    exit_code: int
    stdout: str
    stderr: str


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _git(repo: Path, *args: str, check: bool = True) -> subprocess.CompletedProcess:
    """Run a git command in the given repo directory."""
    return subprocess.run(
        ["git"] + list(args),
        cwd=str(repo),
        capture_output=True,
        text=True,
        check=check,
        env={
            **os.environ,
            "GIT_AUTHOR_NAME": "Test",
            "GIT_AUTHOR_EMAIL": "test@test.com",
            "GIT_COMMITTER_NAME": "Test",
            "GIT_COMMITTER_EMAIL": "test@test.com",
            "GIT_TERMINAL_PROMPT": "0",
            "GCM_INTERACTIVE": "Never",
            "GIT_SSH_COMMAND": "ssh -oBatchMode=yes",
        },
    )


def _write_file(path: Path, content: str) -> None:
    """Write content to a file, creating parent dirs as needed."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content)


def _write_mock_gh(mock_dir: Path, script_content: str = MOCK_GH_SCRIPT) -> None:
    """Write mock gh script and make executable."""
    gh_path = mock_dir / "gh"
    mock_dir.mkdir(parents=True, exist_ok=True)
    gh_path.write_text(script_content)
    gh_path.chmod(gh_path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _clean_yoke_env(*, extra: Optional[dict[str, str]] = None) -> dict[str, str]:
    """Return a subprocess env without leaked Yoke DB bootstrap state."""
    env = os.environ.copy()
    for key in ("YOKE_DB", "YOKE_ROOT", "YOKE_DB_INIT_DONE",
                "YOKE_DB_INIT_ALLOW"):
        env.pop(key, None)
    if extra:
        env.update(extra)
    return env


def run_merge(
    env: MergeEnv,
    branch: str = TEST_BRANCH,
    target: str = "main",
    extra_args: Optional[list] = None,
    *,
    done_transition: bool = True,
    extra_env: Optional[dict] = None,
    cwd: Optional[Path] = None,
) -> MergeResult:
    """Run the merge-worktree engine and capture output."""
    cmd = [sys.executable, "-m", MERGE_MODULE, branch, target]  # absolute; bare python3 misses .venv deps on a clean runner
    if extra_args:
        cmd.extend(extra_args)

    merge_env = env.env(done_transition=done_transition, extra=extra_env)
    merge_env["PYTHONPATH"] = SOURCE_PYTHONPATH

    result = subprocess.run(
        cmd,
        cwd=str(cwd or env.repo),
        capture_output=True,
        text=True,
        env=merge_env,
    )
    return MergeResult(
        exit_code=result.returncode,
        stdout=result.stdout,
        stderr=result.stderr,
    )


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------
@pytest.fixture
def merge_env(tmp_path: Path, request) -> MergeEnv:
    """Create a fresh test repo environment mirroring the shell _setup_repo()."""
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    worktree = tmp_path / "worktree"
    mock_dir = tmp_path / "mock"
    gh_log = tmp_path / "gh.log"
    yoke_root = tmp_path / "state" / "data"
    db_path = yoke_root / "yoke.db"
    rest_fake_dir = tmp_path / "rest-fakes"

    from yoke_core.domain import db_backend

    if db_backend.is_postgres():
        from runtime.api.fixtures import pg_testdb

        pg_name = pg_testdb.create_test_database()
        prior_pg_dsn = os.environ.get(db_backend.PG_DSN_ENV)
        os.environ[db_backend.PG_DSN_ENV] = pg_testdb.dsn_for_test_database(pg_name)

        def _cleanup_pg() -> None:
            if prior_pg_dsn is not None:
                os.environ[db_backend.PG_DSN_ENV] = prior_pg_dsn
            else:
                os.environ.pop(db_backend.PG_DSN_ENV, None)
            pg_testdb.drop_test_database(pg_name)

        request.addfinalizer(_cleanup_pg)

    # Create gh log file
    gh_log.touch()

    # Write mock gh
    _write_mock_gh(mock_dir)

    # Build PATH: mock gh first, then scripts dir, then system PATH
    test_path = f"{mock_dir}:{SCRIPTS_DIR}:{os.environ['PATH']}"

    # Create bare origin. Pin initial branch to main so the bare repo's
    # HEAD matches the working repo (CI runners without
    # ~/.gitconfig init.defaultBranch default to 'master', which makes
    # the eventual 'git push origin main' fail).
    subprocess.run(
        ["git", "init", "--bare", "--initial-branch=main", str(origin)],
        capture_output=True, check=True,
    )

    # Create main repo with the same initial-branch pin so the first
    # commit lands on main locally and 'push origin main' resolves.
    subprocess.run(
        ["git", "init", "--initial-branch=main", str(repo)],
        capture_output=True, check=True,
    )
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "config", "user.email", "test@test.com")
    _git(repo, "config", "user.name", "Test")

    yoke_root.mkdir(parents=True, exist_ok=True)
    _pythonpath = SOURCE_PYTHONPATH
    subprocess.run(
        [sys.executable, "-m", "yoke_core.cli.db_router", "init"],
        cwd=str(repo),
        capture_output=True,
        check=True,
        env=_clean_yoke_env(
            extra={
            "YOKE_ROOT": str(yoke_root),
            "PYTHONPATH": _pythonpath,
            "YOKE_DB_INIT_ALLOW": "1",
        }),
    )

    # Seed yoke project + github PAT + items row via shared helper so
    # the REST precondition resolves for every merge subprocess test.
    from runtime.api.merge_worktree_test_db import _seed_yoke_project_with_pat
    _seed_conn = db_backend.connect()
    try:
        _seed_yoke_project_with_pat(
            _seed_conn,
            repo_path=str(repo),
            item_id=TEST_ITEM_ID,
            branch=TEST_BRANCH,
        )
        _seed_conn.commit()
    finally:
        _seed_conn.close()

    # Create .gitignore for generated views
    _write_file(repo / ".gitignore", ".yoke/BOARD.md\n.yoke/BOARD.md.ts\n")

    # Initial commit + push
    _write_file(repo / "README.md", "initial\n")
    _write_file(repo / ".yoke" / "BOARD.md", "# Board\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-m", "initial commit")
    _git(repo, "push", "origin", "main")

    # Create test branch and worktree
    _git(repo, "branch", TEST_BRANCH)
    _git(repo, "worktree", "add", str(worktree), TEST_BRANCH)

    # Make a commit on the test branch
    _git(worktree, "config", "user.email", "test@test.com")
    _git(worktree, "config", "user.name", "Test")
    _write_file(worktree / "feature.txt", "feature work\n")
    _git(worktree, "add", "feature.txt")
    _git(worktree, "commit", "-m", "feature work")
    _git(worktree, "push", "origin", TEST_BRANCH)

    # Seed happy-path REST fakes so tests that exercise the full merge
    # flow (prepare → conflict → execute → post-merge cleanup) succeed
    # without each having to author its own canned responses. Tests that
    # need a different shape overwrite the relevant filename via
    # `runtime.api.merge_worktree_test_rest_fakes` helpers.
    from runtime.api import merge_worktree_test_rest_fakes as _rest_fakes

    _rest_fakes.write_happy_path(
        rest_fake_dir, branch=TEST_BRANCH, origin_path=str(origin)
    )

    return MergeEnv(
        tmpdir=tmp_path,
        repo=repo,
        worktree=worktree,
        origin=origin,
        mock_dir=mock_dir,
        gh_log=gh_log,
        yoke_root=yoke_root,
        db_path=db_path,
        test_path=test_path,
        rest_fake_dir=rest_fake_dir,
    )


# Re-export sentinel: importing this module via pytest still runs zero tests.
# All test classes live in sibling modules (prepare/execute/post).
_SHARED_INFRASTRUCTURE_ONLY = True
