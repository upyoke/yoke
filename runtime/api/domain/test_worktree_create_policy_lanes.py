"""Worktree creation coverage for workflow-required lane roles."""

from __future__ import annotations

import os
import subprocess

from runtime.api.domain.test_worktree_create_multiworktree import (
    _config_path,
    seed_multiworktree_epic,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
)
from yoke_core.domain import direct_workflow_worktree_preflight
from yoke_core.domain.item_worktree_schema import ensure_item_worktree_schema
from yoke_core.domain.item_worktrees import list_item_worktrees
from yoke_core.domain import worktree_create
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
        yoke_db,
        99200,
        branches,
        str(git_repo),
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
        entry.branch for entry in result.worktrees if entry.lane_role == "worker"
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
            "(id, title, status, project_id, project_sequence) "
            "VALUES (99220, 'Direct document execution', "
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
    assert [(row["branch"], row["lane_role"]) for row in rows] == [
        ("YOK-99220", "worker")
    ]


def test_worktree_creation_reports_lane_persistence_failure(
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
            "VALUES (99222, 'Persistence boundary', "
            "'refined-idea', 1, 99222)",
        )
        pin_test_item_workflow(conn, 99222, "blitz")
        conn.commit()
    finally:
        conn.close()

    def refuse_persistence(*_args, **_kwargs):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(
        worktree_create,
        "persist_item_worktrees",
        refuse_persistence,
    )
    result = worktree_create.create_worktree(
        99222,
        repo_root=str(git_repo),
        config_path=_config_path(git_repo),
        db_path=yoke_db,
    )

    assert result.created is True
    assert result.error is not None
    assert "item-lane persistence failed" in result.error
    assert os.path.isdir(result.path)


class _DashRelay:
    """Canned ``call_dispatcher`` for the Dash path-claim preparation.

    Routes ``claims.work.holder_get`` and ``claims.path.survey_ensure``
    and records the routed function ids + payloads so the test can prove
    the preparation relays both reads/writes instead of opening a local
    Postgres connection.
    """

    def __init__(self, *, holder: dict | None, ensure_success: bool = True):
        self._holder = holder
        self._ensure_success = ensure_success
        self.calls: list[dict] = []

    def __call__(self, *, function_id, target, payload=None, **_kwargs):
        self.calls.append(
            {"function_id": function_id, "target": target, "payload": payload}
        )
        if function_id == "claims.work.holder_get":
            return FunctionCallResponse(
                success=True, function=function_id, version="v1",
                result={"holder": self._holder},
            )
        if function_id == "claims.path.survey_ensure":
            if self._ensure_success:
                return FunctionCallResponse(
                    success=True, function=function_id, version="v1",
                    result={"claim_id": 7},
                )
            return FunctionCallResponse(
                success=False, function=function_id, version="v1",
                error=FunctionError(code="survey_ensure_failed", message="boom"),
            )
        raise AssertionError(f"unexpected function id {function_id!r}")

    @property
    def routed_ids(self) -> list[str]:
        return [c["function_id"] for c in self.calls]


def _patch_dash_relay(monkeypatch, relay: _DashRelay) -> None:
    monkeypatch.setattr(
        "yoke_core.api.service_client_structured_api_adapter.call_dispatcher",
        relay,
    )


def test_dash_path_claim_relays_holder_get_then_survey_ensure(monkeypatch):
    relay = _DashRelay(holder={"session_id": "claim-session"})
    _patch_dash_relay(monkeypatch, relay)

    error = direct_workflow_worktree_preflight._prepare_dash_path_claim(
        item_id=99230,
        touch_paths=("src/dash.py",),
        integration_target="main",
    )

    assert error is None
    assert relay.routed_ids == [
        "claims.work.holder_get",
        "claims.path.survey_ensure",
    ]
    holder_call, ensure_call = relay.calls
    assert holder_call["target"].item_id == 99230
    assert ensure_call["payload"]["touch_paths"] == ["src/dash.py"]
    assert ensure_call["payload"]["integration_target"] == "main"


def test_dash_path_claim_without_live_work_claim_refuses(monkeypatch):
    relay = _DashRelay(holder=None)
    _patch_dash_relay(monkeypatch, relay)

    error = direct_workflow_worktree_preflight._prepare_dash_path_claim(
        item_id=99230,
        touch_paths=("src/dash.py",),
        integration_target="main",
    )

    assert error == "Dash path-claim preparation has no live item work claim"
    # survey_ensure must not run when there is no live work-claim holder.
    assert relay.routed_ids == ["claims.work.holder_get"]


def test_dash_path_claim_surfaces_survey_ensure_failure(monkeypatch):
    relay = _DashRelay(
        holder={"session_id": "claim-session"}, ensure_success=False
    )
    _patch_dash_relay(monkeypatch, relay)

    error = direct_workflow_worktree_preflight._prepare_dash_path_claim(
        item_id=99230,
        touch_paths=("src/dash.py",),
        integration_target="main",
    )

    assert error == "boom"
