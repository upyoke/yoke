"""CLI-level tests for ``python3 -m yoke_core.domain.worktree paths``.

These tests invoke the Python path-resolver CLI via subprocess so that
stdout / stderr / exit code behavior is exercised directly against the
entrypoint every caller uses now that the shell launcher has been retired.

Coverage map (shell TEST → pytest test):
    T1  CLAUDE_PROJECT_DIR override → TestPathsMain.test_claude_project_dir_override
    T2  git rev-parse fallback      → TestPathsMain.test_git_fallback_resolves_repo_root
    T3  main mode from worktree     → TestPathsMain.test_main_from_worktree
    T4  worktree mode from worktree → TestPathsMain.test_worktree_from_worktree
    T5  main-file mode              → TestPathsMain.test_main_file_returns_absolute_path
    T6  yoke-root from worktree   → TestPathsMain.test_yoke_root_from_worktree
    T7  db mode retired guard       → TestPathsMain.test_db_mode_refuses_retired_path_authority
    T8  no arguments                → TestPathsMain.test_no_args_prints_usage
    T9  outside git repo            → TestPathsMain.test_outside_git_repo_errors
    T10 named path modes            → TestPathsMain.test_named_modes_config /
                                      test_named_modes_backlog / etc.
    T11 named modes from worktree   → TestPathsMain.test_named_modes_from_worktree_resolve_to_main
    T12+ db 0-byte stray removal    → covered by existing test_worktree.TestResolvePaths.test_db_path_removes_zero_byte_stray
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def yoke_repo(tmp_path: Path) -> Path:
    """Create a minimal yoke-flavored git repo with a worktree."""
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.email", "test@test.com"],
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(repo), "config", "user.name", "Test"],
        check=True,
    )

    # Minimal Yoke marker tree.
    (repo / ".yoke").mkdir()
    (repo / ".yoke" / "config.json").write_text('{"schema_version": 1}\n')
    (repo / ".yoke" / "lint-config").write_text("mode=deny\n")
    (repo / "backlog").mkdir()
    (repo / "backlog" / ".counter").write_text("1\n")
    (repo / "docs").mkdir()
    (repo / "runtime").mkdir()
    (repo / "runtime" / "api").mkdir()  # needed for _RP_REPO_ROOT resolution
    (repo / "README.md").write_text("seed\n")
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "commit", "-q", "-m", "init"],
        check=True,
    )
    subprocess.run(["git", "-C", str(repo), "branch", "-M", "main"], check=True)
    return repo


@pytest.fixture
def yoke_worktree(yoke_repo: Path) -> Path:
    """Create a linked worktree under ``yoke_repo/.worktrees/<branch>``."""
    branch = "YOK-1"
    wt_path = yoke_repo / ".worktrees" / branch
    wt_path.parent.mkdir(exist_ok=True)
    subprocess.run(
        ["git", "-C", str(yoke_repo), "worktree", "add", str(wt_path), "-b", branch, "main"],
        check=True,
        capture_output=True,
    )
    return wt_path


# Resolve the repo root that contains the ``yoke_core.domain.worktree``
# module so subprocess invocations can import it the same way the shell
# launcher does (via its computed ``_RP_REPO_ROOT`` → ``PYTHONPATH`` export).
_MODULE_REPO_ROOT = str(Path(__file__).resolve().parents[3])


def _run_paths(
    mode: str,
    *extra_args: str,
    cwd: Path,
    env_overrides: dict | None = None,
) -> subprocess.CompletedProcess:
    """Invoke ``python3 -m yoke_core.domain.worktree paths`` like the shell launcher does."""
    env = os.environ.copy()
    # Strip any inherited YOKE_* that would mask the CWD-based resolution.
    for key in (
        "YOKE_ROOT",
        "YOKE_RESOLVE_CWD",
        "CLAUDE_PROJECT_DIR",
        "YOKE_REPO_ROOT",
        "YOKE_MACHINE_CONFIG_FILE",
        "YOKE_MACHINE_HOME",
        "YOKE_HOME",
    ):
        env.pop(key, None)
    # The shell launcher prepends the worktree repo root to PYTHONPATH so
    # ``python3 -m yoke_core.domain.worktree`` resolves even from a
    # temporary CWD that has no ``yoke/api`` tree of its own.
    existing_pp = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{_MODULE_REPO_ROOT}{os.pathsep}{existing_pp}" if existing_pp else _MODULE_REPO_ROOT
    )
    if env_overrides:
        env.update(env_overrides)
    cmd = [sys.executable, "-m", "yoke_core.domain.worktree", "paths", mode, *extra_args]
    return subprocess.run(cmd, cwd=str(cwd), env=env, capture_output=True, text=True)


def _canon(path: Path) -> str:
    """Canonicalize a path the way the shell tests did (resolve /private/tmp)."""
    return os.path.realpath(str(path))


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestPathsMain:
    def test_no_args_prints_usage(self, yoke_repo: Path):
        """Shell T8: No arguments — exits non-zero with usage message."""
        cmd = [sys.executable, "-m", "yoke_core.domain.worktree", "paths"]
        env = os.environ.copy()
        for key in ("YOKE_ROOT", "YOKE_RESOLVE_CWD", "CLAUDE_PROJECT_DIR", "YOKE_REPO_ROOT"):
            env.pop(key, None)
        existing_pp = env.get("PYTHONPATH", "")
        env["PYTHONPATH"] = (
            f"{_MODULE_REPO_ROOT}{os.pathsep}{existing_pp}" if existing_pp else _MODULE_REPO_ROOT
        )
        r = subprocess.run(cmd, cwd=str(yoke_repo), env=env, capture_output=True, text=True)
        assert r.returncode == 1
        assert "Usage" in r.stderr

    def test_outside_git_repo_errors(self, tmp_path: Path):
        """Shell T9: Outside git repo — error surfaced on stderr."""
        other = tmp_path / "no-git"
        other.mkdir()
        r = _run_paths("main", cwd=other)
        assert r.returncode != 0
        assert "Error" in r.stderr or "error" in r.stderr

    # --- main / worktree / main-file ---------------------------------------

    def test_claude_project_dir_override(self, yoke_repo: Path):
        """Shell T1: CLAUDE_PROJECT_DIR set — returns that directory."""
        r = _run_paths(
            "main",
            cwd=yoke_repo,
            env_overrides={"CLAUDE_PROJECT_DIR": str(yoke_repo)},
        )
        assert r.returncode == 0
        assert _canon(Path(r.stdout.strip())) == _canon(yoke_repo)

    def test_git_fallback_resolves_repo_root(self, yoke_repo: Path):
        """Shell T2: git rev-parse fallback — returns repo root."""
        r = _run_paths("main", cwd=yoke_repo)
        assert r.returncode == 0
        assert _canon(Path(r.stdout.strip())) == _canon(yoke_repo)

    def test_main_from_worktree(self, yoke_repo: Path, yoke_worktree: Path):
        """Shell T3: main mode from worktree — returns main repo root."""
        r = _run_paths("main", cwd=yoke_worktree)
        assert r.returncode == 0
        assert _canon(Path(r.stdout.strip())) == _canon(yoke_repo)

    def test_worktree_from_worktree(self, yoke_repo: Path, yoke_worktree: Path):
        """Shell T4: worktree mode from worktree — returns worktree root."""
        r = _run_paths("worktree", cwd=yoke_worktree)
        assert r.returncode == 0
        assert _canon(Path(r.stdout.strip())) == _canon(yoke_worktree)

    def test_main_file_returns_absolute_path(self, yoke_repo: Path):
        """Shell T5: main-file mode — returns absolute path to file."""
        r = _run_paths("main-file", "README.md", cwd=yoke_repo)
        assert r.returncode == 0
        assert _canon(Path(r.stdout.strip())) == _canon(yoke_repo / "README.md")

    def test_main_file_missing_arg_errors(self, yoke_repo: Path):
        """main-file without a rel path argument errors out."""
        r = _run_paths("main-file", cwd=yoke_repo)
        assert r.returncode != 0
        assert "main-file requires" in r.stderr

    # --- yoke-root / db (worktree normalization) -------------------------

    def test_yoke_root_from_worktree(self, yoke_repo: Path, yoke_worktree: Path):
        """Shell T6: yoke-root mode from worktree — returns main yoke dir."""
        r = _run_paths("yoke-root", cwd=yoke_worktree)
        assert r.returncode == 0
        assert _canon(Path(r.stdout.strip())) == _canon(yoke_repo / ".yoke")

    def test_db_mode_refuses_retired_path_authority(
        self, yoke_repo: Path, yoke_worktree: Path
    ):
        """Shell T7: db mode refuses retired root SQLite path authority."""
        r = _run_paths(
            "db",
            cwd=yoke_worktree,
            env_overrides={"YOKE_ROOT": str(yoke_worktree / ".yoke")},
        )
        assert r.returncode != 0
        assert "SQLite authority retired/guarded" in r.stderr
        assert str(yoke_repo / ".yoke" / "yoke.db") in r.stderr

    # --- named path modes (T10, T11) ---------------------------------------

    @pytest.mark.parametrize(
        "mode,suffix",
        [
            ("config", None),
            ("config-example", None),
            ("backlog", "backlog"),
            ("board", ".yoke/BOARD.md"),
            ("docs", "docs"),
            ("epics", "epics"),
            ("ouroboros", "ouroboros"),
            ("backups", ".yoke/backups"),
        ],
    )
    def test_named_modes_resolve_from_main(
        self, yoke_repo: Path, mode: str, suffix: str
    ):
        """Shell T10: Each named mode resolves to the main repo path."""
        machine_config = yoke_repo / ".yoke" / "config.json"
        r = _run_paths(
            mode,
            cwd=yoke_repo,
            env_overrides={"YOKE_MACHINE_CONFIG_FILE": str(machine_config)},
        )
        assert r.returncode == 0, f"{mode} failed: {r.stderr}"
        expected = _canon(machine_config if suffix is None else yoke_repo / suffix)
        assert _canon(Path(r.stdout.strip())) == expected

    @pytest.mark.parametrize(
        "mode,suffix",
        [
            ("config", None),
            ("backlog", "backlog"),
            ("board", ".yoke/BOARD.md"),
            ("docs", "docs"),
        ],
    )
    def test_named_modes_from_worktree_resolve_to_main(
        self,
        yoke_repo: Path,
        yoke_worktree: Path,
        mode: str,
        suffix: str,
    ):
        """Shell T11: Named modes from a worktree still resolve to the main repo."""
        machine_config = yoke_repo / ".yoke" / "config.json"
        r = _run_paths(
            mode,
            cwd=yoke_worktree,
            env_overrides={"YOKE_MACHINE_CONFIG_FILE": str(machine_config)},
        )
        assert r.returncode == 0, f"{mode} from worktree failed: {r.stderr}"
        expected = _canon(machine_config if suffix is None else yoke_repo / suffix)
        assert _canon(Path(r.stdout.strip())) == expected

    def test_unknown_mode_errors(self, yoke_repo: Path):
        """Unknown mode surfaces a specific error message."""
        r = _run_paths("not-a-mode", cwd=yoke_repo)
        assert r.returncode != 0
        assert "not-a-mode" in r.stderr or "Unknown" in r.stderr
