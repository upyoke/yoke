"""Safety proofs for automatic managed-worktree pruning."""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

from yoke_core.engines.merge_worktree_safe_prune import prune_managed_worktrees


class _Rows:
    def __init__(self, rows=()):
        self._rows = list(rows)

    def fetchall(self):
        return list(self._rows)

    def fetchone(self):
        return self._rows[0] if self._rows else None


class _Conn:
    def __init__(
        self,
        branch: str,
        *,
        terminal=True,
        claimed=False,
        mixed_owner=False,
        path_claimed=False,
    ):
        self.branch = branch
        self.terminal = terminal
        self.claimed = claimed
        self.mixed_owner = mixed_owner
        self.path_claimed = path_claimed
        self.closed = False

    def execute(self, sql, params=()):
        if "FROM items WHERE worktree" in sql:
            if params == (self.branch,):
                if self.mixed_owner:
                    return _Rows([(1, "done"), (2, "implementing")])
                return _Rows([(1, "done" if self.terminal else "implementing")])
            return _Rows()
        if "FROM epic_tasks" in sql or "FROM epic_dispatch_chains" in sql:
            return _Rows()
        if "FROM work_claims" in sql:
            return _Rows([(1,)]) if self.claimed else _Rows()
        if "FROM path_claims" in sql:
            return _Rows([(1,)]) if self.path_claimed else _Rows()
        if "FROM harness_sessions" in sql:
            return _Rows()
        raise AssertionError(f"unexpected SQL: {sql}")

    def close(self):
        self.closed = True


def _git(path: Path, *args: str, check: bool = True):
    return subprocess.run(
        ["git", *args],
        cwd=path,
        capture_output=True,
        text=True,
        check=check,
    )


def _repo(tmp_path: Path, branch: str = "codex/terminal"):
    origin = tmp_path / "origin.git"
    repo = tmp_path / "repo"
    _git(tmp_path, "init", "--bare", "--initial-branch=main", str(origin))
    _git(tmp_path, "init", "--initial-branch=main", str(repo))
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    (repo / "README.md").write_text("base\n", encoding="utf-8")
    (repo / ".gitignore").write_text(
        "\n".join(
            (
                "__pycache__/",
                ".pytest_cache/",
                ".ruff_cache/",
                ".venv/",
                "*.egg-info/",
                "build/",
                "node_modules/",
                ".next/",
                ".vite/",
                ".private/",
            )
        )
        + "\n",
        encoding="utf-8",
    )
    _git(repo, "add", "README.md", ".gitignore")
    _git(repo, "commit", "-m", "base")
    _git(repo, "remote", "add", "origin", str(origin))
    _git(repo, "push", "-u", "origin", "main")
    worktree = repo / ".worktrees" / "terminal"
    _git(repo, "worktree", "add", "-b", branch, str(worktree), "main")
    return repo, worktree, branch


def _parent(repo: Path, conn: _Conn):
    lines: list[str] = []

    def run_git(argv, cwd=None, capture=False):
        return _git(Path(cwd or repo), *argv, check=False)

    return SimpleNamespace(
        _run_git=run_git,
        _connect=lambda: conn,
        _print=lambda line, **_kwargs: lines.append(line),
    ), lines


def test_clean_terminal_merged_worktree_and_branch_are_pruned(tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    conn = _Conn(branch)
    parent, lines = _parent(repo, conn)

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert not worktree.exists()
    assert _git(repo, "branch", "--list", branch).stdout.strip() == ""
    assert any("Pruned terminal merged worktree" in line for line in lines)
    assert conn.closed


def test_dirty_terminal_worktree_is_preserved(tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    (worktree / "evidence.txt").write_text("keep me\n", encoding="utf-8")
    parent, lines = _parent(repo, _Conn(branch))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert branch in _git(repo, "branch", "--list", branch).stdout
    assert any("dirty or unverifiable" in line for line in lines)


def test_known_python_and_node_caches_are_removed_before_prune(tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    cache_files = (
        worktree / "__pycache__" / "module.pyc",
        worktree / ".pytest_cache" / "state",
        worktree / ".ruff_cache" / "state",
        worktree / ".venv" / "pyvenv.cfg",
        worktree / "packages" / "core" / "build" / "wheel",
        worktree / "packages" / "core" / "src" / "core.egg-info" / "PKG-INFO",
        worktree / "webapp" / "node_modules" / "pkg" / "index.js",
        worktree / "webapp" / ".next" / "cache" / "data",
        worktree / "webapp" / ".vite" / "cache" / "data",
    )
    for path in cache_files:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("generated\n", encoding="utf-8")
    parent, _lines = _parent(repo, _Conn(branch))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert not worktree.exists()
    assert _git(repo, "branch", "--list", branch).stdout.strip() == ""


def test_unknown_ignored_content_is_preserved(tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    protected = worktree / ".private" / "operator-note"
    protected.parent.mkdir(parents=True)
    protected.write_text("keep me\n", encoding="utf-8")
    parent, lines = _parent(repo, _Conn(branch))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert protected.read_text(encoding="utf-8") == "keep me\n"
    assert worktree.exists()
    assert any("dirty or unverifiable" in line for line in lines)


def test_active_claim_preserves_terminal_worktree(tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    parent, lines = _parent(repo, _Conn(branch, claimed=True))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert any("actively claimed" in line for line in lines)


def test_active_item_owned_path_claim_preserves_terminal_worktree(tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    parent, lines = _parent(repo, _Conn(branch, path_claimed=True))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert branch in _git(repo, "branch", "--list", branch).stdout
    assert any("actively claimed" in line for line in lines)


def test_unmerged_terminal_worktree_is_preserved(tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    (worktree / "feature.txt").write_text("new\n", encoding="utf-8")
    _git(worktree, "add", "feature.txt")
    _git(worktree, "commit", "-m", "unmerged")
    parent, lines = _parent(repo, _Conn(branch))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert any("unmerged worktree branch" in line for line in lines)


def test_nonterminal_owner_preserves_merged_worktree(tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    parent, _lines = _parent(repo, _Conn(branch, terminal=False))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert branch in _git(repo, "branch", "--list", branch).stdout


def test_terminal_and_nonterminal_owners_sharing_branch_are_preserved(
    tmp_path: Path,
):
    repo, worktree, branch = _repo(tmp_path)
    parent, _lines = _parent(repo, _Conn(branch, mixed_owner=True))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert branch in _git(repo, "branch", "--list", branch).stdout
