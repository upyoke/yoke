"""Worktree creation coverage for workflow-required lane roles."""

from __future__ import annotations

import os
import subprocess

from runtime.api.domain.test_worktree_create_multiworktree import (
    _config_path,
    seed_multiworktree_epic,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import direct_workflow_worktree_preflight
from yoke_core.domain import dash_path_claim_posture
from yoke_core.domain.item_worktree_schema import ensure_item_worktree_schema
from yoke_core.domain.item_worktrees import list_item_worktrees
from yoke_core.domain.worktree import create_worktree
from yoke_core.domain.worktree_test_helpers import pin_test_item_workflow


def test_epic_creates_integration_lane_and_each_worker(
    git_repo,
    yoke_db,
):
    branches = [
        "epic-99200-cli",
        "epic-99200-core",
        "epic-99200-tests",
    ]
    entries = seed_multiworktree_epic(
        yoke_db, 99200, branches, str(git_repo),
    )

    result = create_worktree(
        99200,
        repo_root=str(git_repo),
        config_path=_config_path(git_repo),
        db_path=yoke_db,
    )

    assert result.error is None, result.error
    assert result.created is True
    assert len(result.worktrees) == len(branches) + 1
    assert result.worktrees[0].lane_role == "integration"
    assert result.worktrees[0].branch == "YOK-99200"
    assert {
        entry.branch
        for entry in result.worktrees
        if entry.lane_role == "worker"
    } == set(branches)
    for branch, path in entries:
        assert os.path.isdir(path), f"missing worktree at {path}"
        current = subprocess.run(
            ["git", "branch", "--show-current"],
            cwd=path,
            capture_output=True,
            text=True,
        )
        assert current.stdout.strip() == branch

    listing = subprocess.run(
        ["git", "-C", str(git_repo), "worktree", "list", "--porcelain"],
        capture_output=True,
        text=True,
    )
    for _, path in entries:
        assert path in listing.stdout
    assert result.worktrees[0].path in listing.stdout


def test_blitz_creates_and_registers_a_real_default_worker_lane(
    git_repo,
    yoke_db,
    monkeypatch,
):
    conn = connect_test_db(yoke_db)
    try:
        ensure_item_worktree_schema(conn)
        conn.execute(
            "INSERT INTO items "
            "(id, title, type, status, project_id, project_sequence) "
            "VALUES (99220, 'Direct document execution', 'blitz', "
            "'refined-idea', 1, 99220)",
        )
        pin_test_item_workflow(conn, 99220, "blitz")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setenv("YOKE_SESSION_ID", "blitz-lane-owner")

    result = create_worktree(
        99220,
        repo_root=str(git_repo),
        config_path=_config_path(git_repo),
        db_path=yoke_db,
    )

    assert result.error is None, result.error
    assert len(result.worktrees) == 1
    assert result.worktrees[0].lane_role == "worker"
    assert os.path.isdir(result.worktrees[0].path)
    conn = connect_test_db(yoke_db)
    try:
        rows = list_item_worktrees(conn, 99220, active_only=True)
    finally:
        conn.close()
    assert [
        (row["branch"], row["lane_role"])
        for row in rows
    ] == [("YOK-99220", "worker")]


def test_dash_path_claim_uses_the_live_work_claim_session(monkeypatch):
    captured = {}

    class _Cursor:
        def fetchone(self):
            return {"session_id": "claim-session"}

    class _Connection:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def execute(self, query, params):
            assert "FROM work_claims" in query
            assert params == (99230,)
            return _Cursor()

    monkeypatch.setattr(
        direct_workflow_worktree_preflight,
        "connect",
        lambda: _Connection(),
    )
    monkeypatch.setattr(
        dash_path_claim_posture,
        "ensure_survey_path_claim",
        lambda _conn, **kwargs: captured.update(kwargs),
    )

    error = direct_workflow_worktree_preflight._prepare_dash_path_claim(
        item_id=99230,
        touch_paths=("src/dash.py",),
        integration_target="main",
    )

    assert error is None
    assert captured["session_id"] == "claim-session"
