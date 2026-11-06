# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.domain.worktree_create_test_support import _placeholder as _placeholder

import os

import subprocess

import sys

import pytest

from yoke_core.domain import db_backend

from yoke_core.domain import worktree as worktree_cli

from yoke_core.domain import yok_n_parser

from yoke_core.domain.item_worktrees import record_item_worktree

from yoke_core.domain.worktree import create_worktree

from runtime.api.domain.worktree_test_helpers import pin_test_item_workflow

from runtime.api.fixtures.file_test_db import connect_test_db

from runtime.api.domain.worktree_test_helpers import seed_lane_item


def seed_multiworktree_epic(db_path: str, epic_id: int, branches, repo_root: str):
    """Seed an item plus universal worker lanes for *branches*.

    Returns the ordered ``(branch, worktree_path)`` list the unified
    creator should iterate over.
    """
    conn = connect_test_db(db_path)
    p = _placeholder(conn)
    conn.execute(
        "INSERT INTO items "
        "(id, title, status, project_id, project_sequence) "
        f"VALUES ({p}, 'Multi-worktree epic', 'implementing', {p}, {p}) "
        "ON CONFLICT(id) DO UPDATE SET title=excluded.title, "
        "status=excluded.status, "
        "project_id=excluded.project_id, project_sequence=excluded.project_sequence",
        (epic_id, 1, epic_id),
    )
    pin_test_item_workflow(conn, epic_id, "epic")
    entries = []
    for branch in branches:
        wt_path = os.path.join(repo_root, ".worktrees", branch)
        lane = record_item_worktree(
            conn,
            item_id=epic_id,
            branch=branch,
            path=wt_path,
            lane_role="worker",
        )
        conn.execute(
            "INSERT INTO epic_dispatch_chains "
            f"(epic_id, item_worktree_id, queue) VALUES ({p}, {p}, {p}) "
            "ON CONFLICT(epic_id, item_worktree_id) DO UPDATE SET "
            "queue=excluded.queue",
            (epic_id, lane["id"], "[]"),
        )
        entries.append((branch, wt_path))
    conn.commit()
    conn.close()
    return entries


def _config_path(git_repo) -> str:
    return str(git_repo / "runtime" / "config")
