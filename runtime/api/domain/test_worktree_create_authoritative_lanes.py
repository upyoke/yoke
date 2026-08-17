"""Additional and hosted authoritative worktree lane materialization."""

from __future__ import annotations

import os
from types import SimpleNamespace

from runtime.api.domain.test_worktree_create_multiworktree import _config_path
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.api import service_client_structured_api_adapter
from yoke_core.domain import worktree_create, worktree_create_db
from yoke_core.domain.item_worktree_lane_creation import (
    create_additional_item_worktree_lane,
)
from yoke_core.domain.item_worktree_schema import ensure_item_worktree_schema
from yoke_core.domain.item_worktrees import list_item_worktrees
from yoke_core.domain.worktree import create_worktree
from runtime.api.domain.worktree_test_helpers import pin_test_item_workflow


def test_blitz_materializes_registered_additional_lanes(
    git_repo,
    yoke_db,
    monkeypatch,
):
    conn = connect_test_db(yoke_db)
    try:
        ensure_item_worktree_schema(conn)
        conn.execute(
            "INSERT INTO items "
            "(id, title, status, project_id, project_sequence) "
            "VALUES (99221, 'Parallel document execution', "
            "'refined-idea', 1, 99221)",
        )
        pin_test_item_workflow(conn, 99221, "blitz")
        conn.commit()
    finally:
        conn.close()
    monkeypatch.setenv("YOKE_SESSION_ID", "blitz-additional-lane-owner")

    default = create_worktree(
        99221,
        repo_root=str(git_repo),
        config_path=_config_path(git_repo),
        db_path=yoke_db,
    )
    assert default.error is None, default.error

    conn = connect_test_db(yoke_db)
    try:
        create_additional_item_worktree_lane(
            conn,
            item_id=99221,
            lane_role="worker",
            branch="blitz-99221-docs",
        )
        create_additional_item_worktree_lane(
            conn,
            item_id=99221,
            lane_role="integration",
            branch="blitz-99221-integration",
        )
    finally:
        conn.close()

    result = create_worktree(
        99221,
        repo_root=str(git_repo),
        config_path=_config_path(git_repo),
        db_path=yoke_db,
    )

    assert result.error is None, result.error
    assert result.branch == "blitz-99221-integration"
    assert {entry.branch for entry in result.worktrees} == {
        "YOK-99221",
        "blitz-99221-docs",
        "blitz-99221-integration",
    }
    conn = connect_test_db(yoke_db)
    try:
        rows = list_item_worktrees(conn, 99221, active_only=True)
    finally:
        conn.close()
    assert all(row["path"] for row in rows)
    assert all(os.path.isdir(row["path"]) for row in rows)


def test_hosted_blitz_materializes_every_authoritative_lane_locally(
    git_repo,
    monkeypatch,
):
    remote_lanes = [
        {
            "id": 61,
            "branch": "YOK-99223",
            "path": "/another-machine/YOK-99223",
            "lane_role": "worker",
        },
        {
            "id": 62,
            "branch": "blitz-99223-docs",
            "path": None,
            "lane_role": "worker",
        },
        {
            "id": 63,
            "branch": "blitz-99223-integration",
            "path": None,
            "lane_role": "integration",
        },
    ]
    persisted = {}
    monkeypatch.setattr(
        worktree_create,
        "item_worktree_authority_is_https",
        lambda: True,
    )
    monkeypatch.setattr(
        worktree_create,
        "prepare_authoritative_item_worktrees",
        lambda _item_id: remote_lanes,
    )
    monkeypatch.setattr(
        worktree_create,
        "persist_item_worktrees",
        lambda item_id, lanes, db_path: persisted.update(
            item_id=item_id,
            lanes=list(lanes),
            db_path=db_path,
        ),
    )

    result = worktree_create.create_worktree(
        99223,
        repo_root=str(git_repo),
        config_path=_config_path(git_repo),
    )

    assert result.error is None, result.error
    assert [entry.branch for entry in result.worktrees] == [
        "blitz-99223-integration",
        "YOK-99223",
        "blitz-99223-docs",
    ]
    assert all(
        entry.path.startswith(str(git_repo / ".worktrees"))
        for entry in result.worktrees
    )
    assert all(os.path.isdir(entry.path) for entry in result.worktrees)
    assert [lane[0] for lane in persisted["lanes"]] == [63, 61, 62]
    assert persisted["db_path"] is None


def test_hosted_lane_prepare_and_path_persistence_use_registered_calls(
    monkeypatch,
):
    calls = []
    lanes = [
        {
            "id": 71,
            "branch": "YOK-99224",
            "path": None,
            "lane_role": "worker",
        },
        {
            "id": 72,
            "branch": "blitz-99224-tests",
            "path": None,
            "lane_role": "worker",
        },
    ]

    def _dispatch(**kwargs):
        calls.append(kwargs)
        if kwargs["function_id"] == "item_worktrees.list":
            return SimpleNamespace(success=True, result={"worktrees": lanes})
        return SimpleNamespace(success=True, result={})

    monkeypatch.setattr(
        service_client_structured_api_adapter,
        "call_dispatcher",
        _dispatch,
    )
    monkeypatch.setattr(
        worktree_create_db,
        "item_worktree_authority_is_https",
        lambda: True,
    )

    assert worktree_create_db.prepare_authoritative_item_worktrees(99224) == lanes
    worktree_create_db.persist_item_worktrees(
        99224,
        [
            (71, "YOK-99224", "/local/YOK-99224", "worker"),
            (
                72,
                "blitz-99224-tests",
                "/local/blitz-99224-tests",
                "worker",
            ),
        ],
        None,
    )

    assert [call["function_id"] for call in calls] == [
        "item_worktrees.create",
        "item_worktrees.list",
        "item_worktrees.path_record",
        "item_worktrees.path_record",
    ]
    assert calls[0]["payload"] == {}
    assert calls[2]["preconditions"] == {
        "worktree_id": 71,
        "branch": "YOK-99224",
    }
    assert calls[3]["preconditions"] == {
        "worktree_id": 72,
        "branch": "blitz-99224-tests",
    }
