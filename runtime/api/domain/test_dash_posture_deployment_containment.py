"""The deployment gate accepts any candidate containing an item's merge."""

from __future__ import annotations

from runtime.api.domain.dash_posture_deployment_containment_test_support import (
    _bind_lane_head as _bind_lane_head,
    _deploy_posture_item as _deploy_posture_item,
    _git as _git,
    _insert_dash as _insert_dash,
    _release_history as _release_history,
    dash_db_path as dash_db_path,
)


from pathlib import Path

import pytest

from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain import deployment_run_carried_work_source
from yoke_core.domain.dash_posture_gate import evaluate


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


def test_a_first_landing_run_cannot_close_a_newer_undeployed_lane(
    dash_db_path: str,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
):
    """Done after a run of the first landing refuses while the live head is newer.

    Deployment posture stays off: a succeeded first-landing run must not
    close the item when the same-item lane has moved past that run's source.
    """
    repo, merge, tip, _fork = _release_history(tmp_path)
    monkeypatch.setattr(
        deployment_run_carried_work_source,
        "checkout_for_project_id",
        lambda _project_id: repo,
    )
    conn = connect_test_db(dash_db_path)
    try:
        _deploy_posture_item(
            conn, item_id=2309, merge_sha=merge, lineage=merge, posture={},
        )
        _bind_lane_head(conn, item_id=2309, commit_sha=tip)
    finally:
        conn.close()

    refusal = evaluate(item_id=2309, target_status="done", db_path=dash_db_path)
    assert refusal is not None
    assert refusal["error_code"] == "GATE_DASH_DEPLOYMENT_LINEAGE"


def test_a_first_landing_run_still_closes_when_the_lane_matches(
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
        _deploy_posture_item(
            conn, item_id=2310, merge_sha=merge, lineage=merge, posture={},
        )
        _bind_lane_head(conn, item_id=2310, commit_sha=merge)
    finally:
        conn.close()

    assert evaluate(item_id=2310, target_status="done", db_path=dash_db_path) is None
