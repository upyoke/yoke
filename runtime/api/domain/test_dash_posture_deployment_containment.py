"""The deployment gate accepts any candidate containing an item's merge."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import (
    insert_deployment_run,
    insert_item,
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
        from yoke_core.domain.deployment_runs_schema import cmd_init

        cmd_init(db_path)
        conn = connect_test_db(db_path)
        try:
            conn.execute(
                "INSERT INTO actors "
                "(id, kind, system_component, created_at) "
                "VALUES (901, 'human', NULL, %s) ON CONFLICT DO NOTHING",
                (iso8601_now(),),
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


def _deploy_posture_item(conn, *, item_id: int, merge_sha: str, lineage: str) -> None:
    _insert_dash(conn, item_id=item_id, posture={"deployment": True})
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


def test_deploy_posture_accepts_a_batch_tip_containing_the_item_merge(
    dash_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, merge, tip, _fork = _release_history(tmp_path)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )
    conn = connect_test_db(dash_db_path)
    try:
        _deploy_posture_item(conn, item_id=2304, merge_sha=merge, lineage=tip)
    finally:
        conn.close()

    assert evaluate(item_id=2304, target_status="done", db_path=dash_db_path) is None


def test_deploy_posture_accepts_a_candidate_that_is_the_item_merge(
    dash_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, merge, _tip, _fork = _release_history(tmp_path)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )
    conn = connect_test_db(dash_db_path)
    try:
        _deploy_posture_item(conn, item_id=2305, merge_sha=merge, lineage=merge)
    finally:
        conn.close()

    assert evaluate(item_id=2305, target_status="done", db_path=dash_db_path) is None


def test_deploy_posture_refuses_a_candidate_predating_the_item_merge(
    dash_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, merge, _tip, _fork = _release_history(tmp_path)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )
    conn = connect_test_db(dash_db_path)
    try:
        # The candidate is the merge's own parent, so the deployed revision
        # genuinely predates the work it is being credited with.
        parent = _git(repo, "rev-parse", f"{merge}^")
        _deploy_posture_item(conn, item_id=2306, merge_sha=merge, lineage=parent)
    finally:
        conn.close()

    refusal = evaluate(item_id=2306, target_status="done", db_path=dash_db_path)
    assert refusal is not None
    assert refusal["error_code"] == "GATE_DASH_DEPLOYMENT_LINEAGE"


def test_deploy_posture_refuses_a_candidate_on_a_separate_line(
    dash_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    repo, merge, _tip, fork = _release_history(tmp_path)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )
    conn = connect_test_db(dash_db_path)
    try:
        _deploy_posture_item(conn, item_id=2307, merge_sha=merge, lineage=fork)
    finally:
        conn.close()

    refusal = evaluate(item_id=2307, target_status="done", db_path=dash_db_path)
    assert refusal is not None
    assert refusal["error_code"] == "GATE_DASH_DEPLOYMENT_LINEAGE"


def test_deploy_posture_refuses_clearly_when_containment_cannot_be_read(
    dash_db_path: str,
    monkeypatch: pytest.MonkeyPatch,
):
    """No checkout and no readable binding refuses by name, not by guess."""
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: None,
    )
    conn = connect_test_db(dash_db_path)
    try:
        _deploy_posture_item(conn, item_id=2308, merge_sha="d" * 40, lineage="f" * 40)
    finally:
        conn.close()

    refusal = evaluate(item_id=2308, target_status="done", db_path=dash_db_path)
    assert refusal is not None
    assert refusal["error_code"] == "GATE_DASH_DEPLOYMENT_CONTAINMENT_UNDETERMINED"
    assert "project_source_unavailable" in refusal["error"]
    assert "redeploy" in refusal["remediation_hint"]
