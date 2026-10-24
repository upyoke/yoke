"""Tests for yoke_core.domain.lint_destructive_git (typed evaluate)."""

from __future__ import annotations


import os
import pathlib
import subprocess
import tempfile

from yoke_core.domain import lint_destructive_git as ldg


def _payload(command: str, **extra) -> dict:
    p = {
        "tool_name": "Bash",
        "tool_input": {"command": command},
        "session_id": "sess-test",
        "tool_use_id": "tu-test",
        "turn_id": "turn-test",
    }
    p.update(extra)
    return p


def _record_for(payload: dict) -> "ldg.HookContext":
    """Build the HookContext shape the entry-point's CLI helper would build."""
    return ldg._build_context_from_payload(payload)


def _git_run(repo: str, *args: str) -> subprocess.CompletedProcess:
    env = {
        **os.environ,
        "GIT_AUTHOR_NAME": "t",
        "GIT_AUTHOR_EMAIL": "t@x",
        "GIT_COMMITTER_NAME": "t",
        "GIT_COMMITTER_EMAIL": "t@x",
    }
    return subprocess.run(
        ["git", "-C", repo, *args],
        capture_output=True,
        text=True,
        check=False,
        env=env,
        timeout=10,
    )


def _make_repo(initial_files: dict[str, str] | None = None) -> str:
    repo = tempfile.mkdtemp(prefix="ldg-test-")
    _git_run(repo, "init", "--initial-branch=main")
    _git_run(repo, "config", "user.email", "t@x")
    _git_run(repo, "config", "user.name", "t")
    if initial_files:
        for rel, content in initial_files.items():
            full = pathlib.Path(repo) / rel
            full.parent.mkdir(parents=True, exist_ok=True)
            full.write_text(content)
        _git_run(repo, "add", "-A")
        _git_run(repo, "commit", "-m", "init")
    return repo


def _modify(repo: str, rel: str, content: str) -> None:
    full = pathlib.Path(repo) / rel
    full.parent.mkdir(parents=True, exist_ok=True)
    full.write_text(content)
