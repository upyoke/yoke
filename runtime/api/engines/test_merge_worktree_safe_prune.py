"""Safety proofs for automatic managed-worktree pruning.

The DB authority verdict now routes through the transport-aware
``merge.prune.authority_verdict`` relay. These end-to-end proofs drive the
REAL ``handle_prune_authority_verdict`` handler over a fake in-memory
connection (the same controlled-row conn the pre-relay tests used), so the
prune/keep decision for terminal, actively-claimed, dirty, unmerged, and
mixed-owner worktrees is proven unchanged while the engine relays the
verdict instead of opening a bare ``parent._connect()``.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
)
from yoke_core.domain.handlers import merge_engine_internal_ops as _ops
from yoke_core.engines import merge_worktree_safe_prune as _safe_prune
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
        unavailable=False,
    ):
        self.branch = branch
        self.terminal = terminal
        self.claimed = claimed
        self.mixed_owner = mixed_owner
        self.path_claimed = path_claimed
        self.unavailable = unavailable
        self.closed = False

    def __enter__(self):
        if self.unavailable:
            raise RuntimeError("DB authority unavailable")
        return self

    def __exit__(self, *_exc):
        self.close()
        return False

    def execute(self, sql, params=()):
        if "FROM item_worktrees iw JOIN items i" in sql:
            if params and params[0] == self.branch:
                if self.mixed_owner:
                    return _Rows([
                        (11, 1, "done"),
                        (12, 2, "implementing"),
                    ])
                return _Rows([
                    (11, 1, "done" if self.terminal else "implementing")
                ])
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


def _fake_dispatcher(conn: _Conn):
    """Return a ``call_dispatcher`` that runs the real handler over *conn*."""

    def _call(*, function_id, target, payload=None, **_kwargs):
        assert function_id == "merge.prune.authority_verdict"
        request = FunctionCallRequest(
            function=function_id,
            actor=ActorContext(actor_id=None, session_id="s-prune-test"),
            target=target,
            payload=payload or {},
        )
        outcome = _ops.handle_prune_authority_verdict(request)
        return FunctionCallResponse(
            success=outcome.primary_success,
            function=function_id,
            version="v1",
            result=outcome.result_payload or {},
        )

    return _call


def _install(monkeypatch, repo: Path, conn: _Conn):
    lines: list[str] = []

    def run_git(argv, cwd=None, capture=False):
        return _git(Path(cwd or repo), *argv, check=False)

    parent = SimpleNamespace(
        _run_git=run_git,
        _connect=lambda: pytest.fail("must not open a bare parent._connect()"),
        _print=lambda line, **_kwargs: lines.append(line),
    )
    monkeypatch.setattr(_ops, "_connect_rw", lambda: conn)
    monkeypatch.setattr(_safe_prune, "call_dispatcher", _fake_dispatcher(conn))
    return parent, lines


def test_clean_terminal_merged_worktree_and_branch_are_pruned(
    monkeypatch, tmp_path: Path
):
    repo, worktree, branch = _repo(tmp_path)
    parent, lines = _install(monkeypatch, repo, _Conn(branch))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert not worktree.exists()
    assert _git(repo, "branch", "--list", branch).stdout.strip() == ""
    assert any("Pruned terminal merged worktree" in line for line in lines)


def test_dirty_terminal_worktree_is_preserved(monkeypatch, tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    (worktree / "evidence.txt").write_text("keep me\n", encoding="utf-8")
    parent, lines = _install(monkeypatch, repo, _Conn(branch))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert branch in _git(repo, "branch", "--list", branch).stdout
    assert any("dirty or unverifiable" in line for line in lines)


def test_known_python_and_node_caches_are_removed_before_prune(
    monkeypatch, tmp_path: Path
):
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
    parent, _lines = _install(monkeypatch, repo, _Conn(branch))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert not worktree.exists()
    assert _git(repo, "branch", "--list", branch).stdout.strip() == ""


def test_unknown_ignored_content_is_preserved(monkeypatch, tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    protected = worktree / ".private" / "operator-note"
    protected.parent.mkdir(parents=True)
    protected.write_text("keep me\n", encoding="utf-8")
    parent, lines = _install(monkeypatch, repo, _Conn(branch))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert protected.read_text(encoding="utf-8") == "keep me\n"
    assert worktree.exists()
    assert any("dirty or unverifiable" in line for line in lines)


def test_active_claim_preserves_terminal_worktree(monkeypatch, tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    parent, lines = _install(monkeypatch, repo, _Conn(branch, claimed=True))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert any("actively claimed" in line for line in lines)


def test_active_item_owned_path_claim_preserves_terminal_worktree(
    monkeypatch, tmp_path: Path
):
    repo, worktree, branch = _repo(tmp_path)
    parent, lines = _install(monkeypatch, repo, _Conn(branch, path_claimed=True))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert branch in _git(repo, "branch", "--list", branch).stdout
    assert any("actively claimed" in line for line in lines)


def test_unmerged_terminal_worktree_is_preserved(monkeypatch, tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    (worktree / "feature.txt").write_text("new\n", encoding="utf-8")
    _git(worktree, "add", "feature.txt")
    _git(worktree, "commit", "-m", "unmerged")
    parent, lines = _install(monkeypatch, repo, _Conn(branch))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert any("unmerged worktree branch" in line for line in lines)


def test_nonterminal_owner_preserves_merged_worktree(monkeypatch, tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    parent, _lines = _install(monkeypatch, repo, _Conn(branch, terminal=False))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert branch in _git(repo, "branch", "--list", branch).stdout


def test_terminal_and_nonterminal_owners_sharing_branch_are_preserved(
    monkeypatch, tmp_path: Path,
):
    repo, worktree, branch = _repo(tmp_path)
    parent, _lines = _install(monkeypatch, repo, _Conn(branch, mixed_owner=True))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    assert worktree.exists()
    assert branch in _git(repo, "branch", "--list", branch).stdout


def test_unavailable_db_authority_skips_all_pruning(monkeypatch, tmp_path: Path):
    repo, worktree, branch = _repo(tmp_path)
    parent, lines = _install(monkeypatch, repo, _Conn(branch, unavailable=True))

    prune_managed_worktrees(parent=parent, repo_root=str(repo), target="main")

    # Fail closed: the terminal merged worktree is preserved and the skip
    # narrative fires, exactly as the pre-relay bare-connect failure did.
    assert worktree.exists()
    assert branch in _git(repo, "branch", "--list", branch).stdout
    assert any("DB authority unavailable" in line for line in lines)
