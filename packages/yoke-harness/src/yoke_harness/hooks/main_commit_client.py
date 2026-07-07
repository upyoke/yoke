"""Client Git facts for authority-side main-commit hook checks."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Optional

from yoke_contracts.hook_runner.main_commit import (
    CLIENT_GIT_COMMIT_FACTS_KEY,
    CLIENT_GIT_COMMIT_FACTS_SCHEMA,
    effective_staged_set,
    git_invocations,
    is_actual_git_commit,
)
from yoke_contracts.project_contract.strategy_docs_header import (
    StrategyHeaderError,
    content_sha256,
    parse_file_text,
)
from yoke_contracts.project_contract.strategy_docs_paths import slug_from_view_path

from yoke_harness.hooks.local_policy_common import command_from_payload, cwd_from_payload


def _git(cwd: str, *args: str) -> Optional[subprocess.CompletedProcess]:
    try:
        return subprocess.run(
            ["git", "-C", cwd, *args],
            capture_output=True,
            text=True,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return None


def _repo_cwd(payload: dict, repo_path: str = "") -> str:
    return os.path.abspath(repo_path) if repo_path else cwd_from_payload(payload)


def _branch(cwd: str) -> Optional[str]:
    result = _git(cwd, "rev-parse", "--abbrev-ref", "HEAD")
    if result is None or result.returncode != 0:
        return None
    return result.stdout.strip()


def _staged(cwd: str) -> Optional[list[str]]:
    result = _git(cwd, "diff", "--cached", "--name-only")
    if result is None or result.returncode != 0:
        return None
    return [line for line in result.stdout.splitlines() if line.strip()]


def _modified_and_untracked(cwd: str) -> Optional[list[str]]:
    result = _git(cwd, "status", "--porcelain", "-z")
    if result is None or result.returncode != 0:
        return None
    paths: list[str] = []
    entries = iter(result.stdout.split("\0"))
    for entry in entries:
        if len(entry) < 4 or entry[2] != " ":
            continue
        status, path = entry[:2], entry[3:]
        if path:
            paths.append(path)
        if "R" in status or "C" in status:
            next(entries, None)
    return paths


def _index_blob(cwd: str, path: str) -> Optional[str]:
    result = _git(cwd, "show", f":{path}")
    if result is None or result.returncode != 0:
        return None
    return result.stdout


def _worktree_blob(cwd: str, path: str) -> Optional[str]:
    try:
        return (Path(cwd) / path).read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None


def _project_context() -> Optional[str]:
    try:
        from yoke_cli.commands._helpers import client_project_context

        return client_project_context(None)
    except Exception:
        return None


def _strategy_blob_fact(cwd: str, path: str, *, worktree: bool) -> dict:
    slug = slug_from_view_path(path)
    blob = _worktree_blob(cwd, path) if worktree else _index_blob(cwd, path)
    fact = {
        "path": path,
        "slug": slug,
        "source": "worktree" if worktree else "index",
    }
    if blob is None:
        return {**fact, "blob_unreadable": True}
    try:
        header = parse_file_text(blob)
    except StrategyHeaderError as exc:
        return {**fact, "header_error": exc.kind}
    return {
        **fact,
        "header_slug": header.slug,
        "header_updated_at": header.updated_at,
        "header_content_sha256": header.content_sha256,
        "body_sha256": content_sha256(header.body),
    }


def collect_git_commit_facts(payload: dict) -> dict:
    """Return payload-extra facts for a relayed ``git commit`` hook call."""
    command = command_from_payload(payload)
    if not is_actual_git_commit(command):
        return {}
    invocations = [
        (args, repo_path)
        for args, repo_path in git_invocations(command)
        if args[:1] == ["commit"]
    ]
    repo_path = invocations[0][1] if invocations else ""
    cwd = _repo_cwd(payload, repo_path)
    staged = _staged(cwd)
    status_paths = _modified_and_untracked(cwd)
    effective = effective_staged_set(
        command,
        staged,
        modified_and_untracked=status_paths,
    )
    paths = effective.paths if effective is not None else []
    worktree_paths = (
        set(effective.worktree_content_paths) if effective is not None else set()
    )
    strategy_blobs = [
        _strategy_blob_fact(cwd, path, worktree=path in worktree_paths)
        for path in paths
        if slug_from_view_path(path) is not None
    ]
    return {
        CLIENT_GIT_COMMIT_FACTS_KEY: {
            "schema": CLIENT_GIT_COMMIT_FACTS_SCHEMA,
            "is_git_commit": True,
            "repo_cwd": cwd,
            "project_context": _project_context(),
            "branch": _branch(cwd),
            "staged_paths": paths,
            "worktree_content_paths": sorted(worktree_paths),
            "strategy_blobs": strategy_blobs,
            "staged_probe_ok": staged is not None,
            "status_probe_ok": status_paths is not None,
        }
    }


__all__ = ["collect_git_commit_facts"]
