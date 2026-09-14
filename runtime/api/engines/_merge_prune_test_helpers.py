"""A repository and a controlled authority row for lane-prune proofs.

The prune/keep decision is a git fact plus a control-plane verdict, so
these back real repositories with the REAL
``handle_prune_authority_verdict`` handler over a fake in-memory
connection. Both lane-retirement boundaries read them, which is how one
suite can prove the sweep and the landing agree about the same lane.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
)
from yoke_core.domain.handlers import merge_engine_internal_ops as _ops
from yoke_core.engines import merge_worktree_safe_prune as _safe_prune


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
                    return _Rows(
                        [
                            (11, 1, "done"),
                            (12, 2, "implementing"),
                        ]
                    )
                return _Rows([(11, 1, "done" if self.terminal else "implementing")])
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

    git_io = dict(run_git=run_git, emit=lambda line, **_kwargs: lines.append(line))
    monkeypatch.setattr(_ops, "_connect_rw", lambda: conn)
    monkeypatch.setattr(_safe_prune, "call_dispatcher", _fake_dispatcher(conn))
    return git_io, lines
