# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from pathlib import Path

from unittest import mock

import pytest

from runtime.api.domain.lint_session_cwd_test_helpers import (
    seed_item,
    seed_item_claim,
)

from runtime.api.fixtures.machine_config_test import register_machine_checkout

from runtime.api.fixtures.pg_testdb import test_database

from yoke_core.domain import lint_lane_main_write

from yoke_core.domain.lint_lane_main_write_classify import is_write_operation

from yoke_core.domain.lint_lane_main_write_messages import ESCAPE_TOKEN


@pytest.fixture
def conn():
    with test_database() as c:
        yield c


@pytest.fixture
def repo(tmp_path):
    repo_path = tmp_path / "repo"
    (repo_path / ".worktrees").mkdir(parents=True)
    return repo_path


def _seed_lane(conn, repo, *, session_id="sid-lane", item_id=2013):
    register_machine_checkout(
        Path(repo).parent / "machine-config",
        Path(repo),
        project_id=1,
    )
    seed_item(
        conn,
        item_id=item_id,
        branch=f"YOK-{item_id}",
        status="implementing",
        repo_path=repo,
    )
    seed_item_claim(conn, session_id, item_id=item_id)
    worktree = repo / ".worktrees" / f"YOK-{item_id}"
    worktree.mkdir(parents=True, exist_ok=True)
    return worktree


def _bash(command: str, *, cwd: str) -> dict:
    return {
        "session_id": "sid-lane",
        "tool_name": "Bash",
        "cwd": cwd,
        "tool_input": {"command": command},
    }
