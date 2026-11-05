# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import os

import subprocess

from contextlib import nullcontext

from pathlib import Path

from typing import Any, List, Tuple

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item

from yoke_cli.commands import git_hook

from yoke_cli.main import main as cli_main

from yoke_cli.project_install.git_hooks import BootstrapResult, install_git_hooks

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    FunctionCallResponse,
)

from yoke_contracts.git_hook_markers import HEAD_RECORDING_GIT_HOOKS

from yoke_core.domain.handlers import project_snapshot_sync as handler

from yoke_core.domain.item_worktrees import record_item_worktree

from yoke_core.domain.workflow_behavior import LANE_IMPLEMENTATION

_FAKE_LAUNCHER = """#!/bin/sh
hook="$2"
shift 2
printf '%s\\t%s\\t%s\\n' "$hook" "$(git rev-parse HEAD)" "$*" >> "{log}"
"""


def _git(repo: Path, *args: str, env: dict | None = None) -> str:
    return subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True,
        text=True,
        check=True,
        env=env,
    ).stdout.strip()


def _hooked_repo(tmp_path: Path) -> Tuple[Path, dict, Path]:
    repo = tmp_path / "lane"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "test@example.com")
    _git(repo, "config", "user.name", "Test")
    install_git_hooks(repo, BootstrapResult())
    log = tmp_path / "hooks.log"
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    launcher = bin_dir / "yoke"
    launcher.write_text(_FAKE_LAUNCHER.format(log=log), encoding="utf-8")
    launcher.chmod(0o755)
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}"}
    return repo, env, log


def _commit(repo: Path, env: dict, name: str) -> None:
    (repo / name).write_text(name, encoding="utf-8")
    _git(repo, "add", name, env=env)
    _git(repo, "commit", "-q", "-m", name, env=env)


def _fired(log: Path) -> List[Tuple[str, str, List[str]]]:
    """Head-recording invocations since the last read, then clear the log."""
    if not log.exists():
        return []
    rows = []
    for line in log.read_text(encoding="utf-8").splitlines():
        hook, head, args = line.split("\t")
        if hook in HEAD_RECORDING_GIT_HOOKS:
            rows.append((hook, head, args.split()))
    log.unlink()
    return rows


def _bridge(**kwargs: Any) -> FunctionCallResponse:
    outcome = handler.handle_project_snapshot_sync(
        FunctionCallRequest(
            function=kwargs["function_id"],
            actor=ActorContext(session_id="test-session"),
            target=kwargs["target"],
            payload=kwargs["payload"],
        )
    )
    return FunctionCallResponse(
        success=outcome.primary_success,
        function=kwargs["function_id"],
        version="v1",
        result=outcome.result_payload or {},
        error=outcome.error,
    )
