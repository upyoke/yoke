"""Merge A, a release-stage QA failure sends it back for rework, merge B.

The joined proof this session's pieces individually cover, exercised through
real handlers against a real database rather than restated as an inequality:
an item's own next legitimate merge attempt after genuinely returning short
of release is not refused as foreign/stale work, the pinned workflow's own
declared-edge preflight genuinely accepts the release-to-implementing
rework move, A's own deployment-run evidence stays readable once B's
replacement run exists, and a late callback bound to A's terminalized run
is refused rather than silently advancing anything.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import item_merge_receipt_document as receipt_doc
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain.deployment_flow_versioning import cmd_create
from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
)
from yoke_core.domain.workflow_status_transition_preflight import (
    prepare_status_transition,
)

BRANCH = "ITEM-1"
TARGET = "main"
ITEM_ID = 9950
LINEAGE_A = "a" * 40
LINEAGE_B = "b" * 40


def _git(repo: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(repo), *args], check=True, capture_output=True, text=True,
    )
    return result.stdout.strip()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    _git(root, "init", "-q", "-b", TARGET)
    _git(root, "config", "user.email", "test@example.com")
    _git(root, "config", "user.name", "Test")
    (root / "base.txt").write_text("base\n")
    _git(root, "add", "base.txt")
    _git(root, "commit", "-q", "-m", "base")
    _git(root, "checkout", "-q", "-b", BRANCH)
    (root / "feature.py").write_text("first cut\n")
    _git(root, "add", "feature.py")
    _git(root, "commit", "-q", "-m", "implement the feature")
    return root


def _seed_flow_and_run(
    conn: Any, run_id: str, lineage: str, *, status: str = "executing",
) -> None:
    stages = [{"name": "deploy-stage", "step_runner": "auto", "stage_kind": "execution", "scope": "run"}]
    flow_id = f"flow-{run_id}"
    cmd_create(conn, flow_id, "yoke", flow_id, "", json.dumps(stages), status="disabled")
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "current_stage,created_at) VALUES (%s,1,%s,%s,%s,'deploy-stage',%s)",
        (run_id, flow_id, lineage, status, "2026-09-14T00:00:00Z"),
    )
    conn.commit()


def _lane(item_id: int, repo_root: Path) -> landed.LandedLane | None:
    return landed.landed_lane(
        item_id=item_id, branch=BRANCH, target=TARGET,
        repo_root=str(repo_root), project="yoke",
    )


def test_merge_a_then_rework_then_merge_b_preserves_a_and_admits_b(
    repo: Path, test_db: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    insert_item(
        test_db, id=ITEM_ID, project_sequence=ITEM_ID,
        workflow_id="dash", status="release",
    )
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(landed.receipts, "record", lambda *_a, **_k: "")

    # --- Merge A lands: reviewing-implementation -> release ---
    a_commit = _git(repo, "rev-parse", BRANCH)
    _git(repo, "checkout", "-q", TARGET)
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge A", BRANCH)
    a_merge_sha = _git(repo, "rev-parse", TARGET)
    receipt_doc.record_entry(
        test_db, item_id=ITEM_ID, branch=BRANCH, target=TARGET,
        commit_sha=a_commit, merge_sha=a_merge_sha, touched_files=["feature.py"],
    )

    lane_a = _lane(ITEM_ID, repo)
    assert lane_a is not None
    assert (lane_a.commit_sha, lane_a.merge_sha) == (a_commit, a_merge_sha)

    # A's deployment run reaches real, observed evidence before its QA fails.
    _seed_flow_and_run(test_db, "run-a", LINEAGE_A)
    receipt_a = allocate_deployment_stage_receipt(
        test_db, run_id="run-a", stage_name="deploy-stage",
        correlation_id="dispatch-a-1", target_kind="persistent_environment",
        executor="test-runner",
    )
    complete_deployment_stage_receipt(
        test_db, run_id="run-a", receipt_id=int(receipt_a["id"]),
        correlation_id="dispatch-a-1", status="ready", target_name="stage",
        observed_url="https://stage.example.test/", observed_release_lineage=LINEAGE_A,
        executor_receipt="executor://dispatch-a-1",
    )

    # --- A's release-stage QA fails: the item returns to implementing for a
    # fix. The pinned workflow's own declared-edge preflight -- the real
    # canonical status-write gate, not a restated assumption -- genuinely
    # accepts this backward move for every stage it is asked about.
    preflight = prepare_status_transition(
        test_db, item_id=ITEM_ID, target_status="implementing",
        originator_actor_id=None, session_id="rework-session",
    )
    assert preflight.failure is None, preflight.failure
    test_db.execute("UPDATE items SET status='implementing' WHERE id=%s", (ITEM_ID,))
    test_db.commit()

    # A's own run is terminalized once superseded -- it is never mutated in
    # place, only marked done answering for the work it actually observed.
    test_db.execute("UPDATE deployment_runs SET status='cancelled' WHERE id='run-a'")
    test_db.commit()

    # The rework adds a new commit to the SAME branch (unlanded again).
    _git(repo, "checkout", "-q", BRANCH)
    (repo / "feature.py").write_text("fixed\n")
    _git(repo, "add", "feature.py")
    _git(repo, "commit", "-q", "-m", "rework after failed release QA")
    b_commit = _git(repo, "rev-parse", BRANCH)

    # A fresh merge attempt on this same lane, now genuinely short of
    # release again, must not be refused as foreign/stale work.
    assert landed.stale_unlanded_work(
        item_id=ITEM_ID, branch=BRANCH, target=TARGET, repo_root=str(repo),
        recorded_head="", reached_release=False,
    ) == ""
    assert _lane(ITEM_ID, repo) is None  # the stale receipt no longer answers

    # --- Merge B lands; B gets its own replacement run, never A's ---
    _git(repo, "checkout", "-q", TARGET)
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge B", BRANCH)
    b_merge_sha = _git(repo, "rev-parse", TARGET)
    receipt_doc.record_entry(
        test_db, item_id=ITEM_ID, branch=BRANCH, target=TARGET,
        commit_sha=b_commit, merge_sha=b_merge_sha, touched_files=["feature.py"],
    )
    _seed_flow_and_run(test_db, "run-b", LINEAGE_B)

    # The receipt document now answers for B -- current state, not a
    # history of merges -- while A's commit and merge stay permanently
    # reachable in git regardless of what it now names.
    lane_b = _lane(ITEM_ID, repo)
    assert lane_b is not None
    assert (lane_b.commit_sha, lane_b.merge_sha) == (b_commit, b_merge_sha)
    assert _git(repo, "merge-base", "--is-ancestor", a_commit, TARGET) == ""
    assert _git(repo, "merge-base", "--is-ancestor", a_merge_sha, TARGET) == ""

    # A's own observed evidence is untouched by B's existence.
    row = test_db.execute(
        "SELECT status,observed_release_lineage FROM deployment_stage_receipts "
        "WHERE run_id='run-a' AND id=%s", (int(receipt_a["id"]),),
    ).fetchone()
    assert (row["status"], row["observed_release_lineage"]) == ("ready", LINEAGE_A)
    assert test_db.execute(
        "SELECT status FROM deployment_runs WHERE id='run-b'"
    ).fetchone()["status"] == "executing"

    # A late callback bound to A's own terminalized run must be refused
    # outright -- it cannot advance anything, B's run included.
    with pytest.raises(ValueError, match="is not executing stage"):
        allocate_deployment_stage_receipt(
            test_db, run_id="run-a", stage_name="deploy-stage",
            correlation_id="dispatch-a-late", target_kind="persistent_environment",
            executor="test-runner",
        )
    with pytest.raises(ValueError, match="not belong to the authorized run"):
        complete_deployment_stage_receipt(
            test_db, run_id="run-b", receipt_id=int(receipt_a["id"]),
            correlation_id="dispatch-a-1", status="ready", target_name="stage",
            observed_url="https://stage.example.test/",
            observed_release_lineage=LINEAGE_A,
            executor_receipt="executor://dispatch-a-late",
        )
    assert test_db.execute(
        "SELECT status FROM deployment_runs WHERE id='run-b'"
    ).fetchone()["status"] == "executing"
    assert test_db.execute(
        "SELECT status FROM items WHERE id=%s", (ITEM_ID,),
    ).fetchone()["status"] == "implementing"
