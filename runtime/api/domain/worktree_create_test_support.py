# ruff: noqa: E402, F401, F811
"""Shared setup for tests in this directory."""

from __future__ import annotations

import os

import subprocess

from pathlib import Path

from unittest.mock import patch

from yoke_core.domain import db_backend, worktree_create

from yoke_core.domain.project_seed_test_helpers import SEED_PROJECT_IDS

from yoke_core.domain.item_worktrees import (
    list_item_worktrees,
    record_item_worktree,
)

from yoke_core.domain.worktree import (
    create_worktree,
)

from runtime.api.domain.worktree_test_helpers import (
    TEST_ITEM_ID,
    TEST_ITEM_REF,
    pin_test_item_workflow,
)

from yoke_contracts.project_contract.file_line_policy import item_base_config_key

from runtime.api.fixtures.file_test_db import connect_test_db

from runtime.api.fixtures.machine_config_test import register_machine_checkout

from runtime.api.domain.worktree_test_helpers import seed_lane_item


def _placeholder(conn) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _project_id(slug: str = "yoke") -> int:
    return SEED_PROJECT_IDS[slug]


def _seed_project_repo(conn, slug: str, repo_path: str) -> None:
    repo = Path(repo_path)
    register_machine_checkout(repo.parent / "machine-config", repo, _project_id(slug))


def _seed_item(
    conn,
    item_id: int,
    *,
    title: str = "Test",
    status: str = "implementing",
    worktree=None,
    worktree_path=None,
    project: str = "yoke",
    workflow_id: str = "issue",
) -> None:
    p = _placeholder(conn)
    conn.execute(
        "INSERT INTO items "
        "(id, title, status, project_id, project_sequence) "
        f"VALUES ({p}, {p}, {p}, {p}, {p})",
        (
            item_id,
            title,
            status,
            _project_id(project),
            item_id,
        ),
    )
    pin_test_item_workflow(conn, item_id, workflow_id)
    if worktree:
        record_item_worktree(
            conn,
            item_id=item_id,
            branch=worktree,
            path=worktree_path,
            lane_role="implementation",
        )
