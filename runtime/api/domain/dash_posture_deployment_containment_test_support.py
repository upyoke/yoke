# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

from runtime.api.fixtures.actor_roles import seed_project_role

import json

import subprocess

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import (
    insert_deployment_run,
    insert_item,
    insert_item_worktree,
)

from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db

from yoke_core.domain import deployment_run_carried_work_source

from yoke_core.domain.dash_execution import record_dash_evidence

from yoke_core.domain.dash_posture_gate import evaluate

from yoke_core.domain.db_helpers import iso8601_now


@pytest.fixture
def dash_db_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        from yoke_core.domain.deployment_runs_schema_init import cmd_init

        cmd_init(db_path)
        conn = connect_test_db(db_path)
        try:
            conn.execute(
                "INSERT INTO actors "
                "(id, kind, system_component, created_at) "
                "VALUES (901, 'human', NULL, %s) ON CONFLICT DO NOTHING",
                (iso8601_now(),),
            )
            project_id = conn.execute(
                "SELECT id FROM projects WHERE slug='yoke'"
            ).fetchone()[0]
            seed_project_role(
                conn, actor_id=901, project_id=int(project_id), role_name="owner"
            )
            conn.commit()
        finally:
            conn.close()
        yield db_path


def _insert_dash(conn, *, item_id: int, posture: dict) -> None:
    insert_item(
        conn,
        id=item_id,
        workflow_id="dash",
        # The stage `done` is declared from, so a preflight reaches its gates.
        status="reviewing-implementation",
        source="901",
        workflow_posture=json.dumps(posture),
        deployment_flow="flow-test",
    )


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _release_history(tmp_path: Path) -> tuple[Path, str, str, str]:
    """Build a trunk with one item merge and a later batch tip beside a fork.

    The gate's question is ancestry, so the evidence has to be a real history
    rather than a comparison stubbed to answer it: ``merge`` is contained in
    ``tip`` and absent from ``fork``.
    """
    repo = tmp_path / "containment-project"
    repo.mkdir()
    subprocess.run(
        ["git", "init", "-b", "main", str(repo)],
        check=True,
        capture_output=True,
        text=True,
    )
    _git(repo, "config", "user.name", "Yoke Test")
    _git(repo, "config", "user.email", "test@example.com")
    (repo / "release.txt").write_text("baseline\n", encoding="utf-8")
    _git(repo, "add", "release.txt")
    _git(repo, "commit", "-m", "Release baseline")
    baseline = _git(repo, "rev-parse", "HEAD")
    (repo / "release.txt").write_text("item\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Land the item")
    merge = _git(repo, "rev-parse", "HEAD")
    (repo / "release.txt").write_text("later\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Land a later neighbour")
    tip = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "-b", "separate-line", baseline)
    (repo / "release.txt").write_text("separate\n", encoding="utf-8")
    _git(repo, "commit", "-am", "Land on a separate line")
    fork = _git(repo, "rev-parse", "HEAD")
    _git(repo, "checkout", "-q", "main")
    return repo, merge, tip, fork


def _bind_lane_head(conn, *, item_id: int, commit_sha: str) -> None:
    lane = insert_item_worktree(
        conn,
        item_id=item_id,
        branch=f"ITEM-{item_id}",
        path=f"/repo/.worktrees/ITEM-{item_id}",
        state="active",
    )
    conn.execute(
        "UPDATE item_worktrees SET commit_sha = %s, updated_at = %s WHERE id = %s",
        (commit_sha, iso8601_now(), int(lane["id"])),
    )
    conn.commit()


def _deploy_posture_item(
    conn,
    *,
    item_id: int,
    merge_sha: str,
    lineage: str,
    posture: dict | None = None,
) -> None:
    _insert_dash(
        conn,
        item_id=item_id,
        posture={"deployment": True} if posture is None else posture,
    )
    record_dash_evidence(
        conn,
        item_id=item_id,
        result_summary="Merged the Dash.",
        verification_summary="Focused checks passed.",
        verification_status="passed",
        commit_sha="e" * 40,
        merge_sha=merge_sha,
        touched_files=["ui/dash.js"],
        tree_root="/repo/.worktrees/lane",
        tree_head_sha="abc1234",
    )
    run_id = f"run-dash-{item_id}"
    insert_deployment_run(
        conn,
        id=run_id,
        status="succeeded",
        current_stage="complete",
        release_lineage=lineage,
        completed_at=iso8601_now(),
    )
    conn.execute(
        "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
        "VALUES (%s, %s, %s)",
        (run_id, item_id, iso8601_now()),
    )
    conn.commit()
