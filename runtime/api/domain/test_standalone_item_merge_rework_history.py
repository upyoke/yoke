"""Merge A, a real release-QA rejection sends it back, merge B lands.

The joined proof, exercised through the real writers rather than restated
as assumptions: a human rejects the item's scoped release QA, the
release-to-done gate genuinely refuses on that rejection, the registered
lifecycle mutation actually persists the backward move, the item's own
next merge attempt is not refused as foreign work, and B's replacement
run carries its own pinned candidate while A's observed evidence and git
history stay exactly as they were. A late callback bound to A's
terminalized run is refused rather than advancing anything.
"""

from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Any

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _complete_case,
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_qa_stage_wake_delivery import (
    _claim,
    _project,
    seed_session,
)
from runtime.api.fixtures.backlog_inserts import insert_item, insert_item_worktree
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import backlog_update_op
from yoke_core.domain import item_merge_receipt_document as receipt_doc
from yoke_core.domain import standalone_item_merge_landed as landed
from yoke_core.domain.conflict_survey import (
    record_conflict_survey,
    survey_conflicts,
)
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.deployment_qa_run_acceptance import (
    item_qa_acceptance_blockers,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.deployment_qa_stage_materialization import (
    materialize_deployment_qa_stage,
)
from yoke_core.domain.deployment_run_terminalization import terminalize_run
from yoke_core.domain.deployment_stage_receipts import (
    allocate_deployment_stage_receipt,
    complete_deployment_stage_receipt,
)
from yoke_core.domain.handlers.lifecycle_transition import handle_transition
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.work_claim_targets import make_item_target

BRANCH = "ITEM-1"
TARGET = "main"
ITEM_ID = 9950
REVIEWER = 9951
LINEAGE_A = "a" * 40
LINEAGE_B = "b" * 40
SESSION = "rework-session"


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


def _release_run_awaiting_verdict(
    conn: Any, run_id: str, lineage: str, slug: str
) -> int:
    """A frozen run whose item-scoped release QA awaits a human verdict."""
    stages = _stages(
        _plan(conn, slug),
        verdict={
            "mode": "required_human",
            "reviewers": {"mode": "all", "roles": [], "actors": [REVIEWER]},
        },
    )
    _seed_run(
        conn,
        run_id=run_id,
        stages=stages,
        members=(),
        existing_members=(ITEM_ID,),
        release_lineage=lineage,
    )
    materialize_deployment_qa_stage(
        conn,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=ITEM_ID,
    )
    _complete_case(
        conn,
        begin_plan_execution(
            conn,
            deployment_run_id=run_id,
            deployment_stage="item-qa",
            deployment_member_item_id=ITEM_ID,
            actor_id="2",
            session_id=SESSION,
        ),
    )
    pending = deployment_qa_stage_status(
        conn, run_id=run_id, stage_name="item-qa", member_item_id=ITEM_ID
    )
    assert pending["request_id"] is not None
    return int(pending["request_id"])


def _status(conn: Any) -> str:
    return str(
        conn.execute(
            "SELECT status FROM items WHERE id=%s", (ITEM_ID,)
        ).fetchone()["status"]
    )


def _lane(item_id: int, repo_root: Path) -> landed.LandedLane | None:
    return landed.landed_lane(
        item_id=item_id, branch=BRANCH, target=TARGET,
        repo_root=str(repo_root), project="yoke",
    )


def test_merge_a_then_real_qa_rejection_then_merge_b(
    repo: Path, test_db: Any, monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("YOKE_CLAIM_BYPASS", "test-isolation")
    monkeypatch.setattr(backlog_update_op, "run_post_db_sync", lambda **_kw: 0)
    _project(test_db)
    test_db.execute(
        "INSERT INTO actors(id,kind,created_at) VALUES "
        "(%s,'human','2026-09-14T00:00:00Z') ON CONFLICT(id) DO NOTHING",
        (REVIEWER,),
    )
    insert_item(
        test_db, id=ITEM_ID, project_sequence=ITEM_ID,
        workflow_id="dash", status="release",
    )
    monkeypatch.setattr(landed.receipts, "load", lambda *_a, **_k: None)
    monkeypatch.setattr(landed.receipts, "record", lambda *_a, **_k: "")
    # Activation requires the reworking session to own the item and the item
    # to have a live lane — which the rework does, on the same branch.
    seed_session(test_db, SESSION)
    _claim(
        test_db,
        session_id=SESSION,
        target_kind="item",
        scope_json=make_item_target(ITEM_ID).scope_json(),
    )
    insert_item_worktree(
        test_db, item_id=ITEM_ID, branch=BRANCH, path=str(repo), state="active"
    )
    test_db.commit()

    # --- Merge A lands ---
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

    # --- A's release QA is rejected by its authorized human reviewer ---
    request_id = _release_run_awaiting_verdict(
        test_db, "run-a", LINEAGE_A, "rework-release-a"
    )
    receipt_a = test_db.execute(
        "SELECT id,observed_release_lineage,status FROM deployment_stage_receipts "
        "WHERE run_id='run-a'"
    ).fetchone()
    resolve_decision_request(
        test_db,
        request_id,
        actor_id=REVIEWER,
        action="reject",
        note="The deployed stage still serves the previous behavior.",
    )

    # The real release-to-done gate refuses on that recorded verdict.
    blockers = item_qa_acceptance_blockers(test_db, run_id="run-a", item_id=ITEM_ID)
    assert any("was rejected" in reason for reason in blockers), blockers

    # A's run is terminalized through its own writer, never mutated in place.
    terminalize_run(
        "run-a",
        disposition="cancelled",
        reason="release QA rejected; reworking the same item",
        actor_id=REVIEWER,
        session_id=SESSION,
    )
    assert str(
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id='run-a'"
        ).fetchone()["status"]
    ) == "cancelled"

    # --- The item returns to implementing through the registered mutation ---
    assert _status(test_db) == "release"
    # Re-entering implementing is gated on a current conflict survey, and
    # the rework owes one: it is about to touch the same file again.
    record_conflict_survey(
        test_db,
        survey_conflicts(
            test_db, item_id=ITEM_ID, touch_paths=["feature.py"],
            integration_target=TARGET,
        ),
    )
    outcome = handle_transition(
        FunctionCallRequest(
            function="lifecycle.transition.execute",
            actor=ActorContext(actor_id=str(REVIEWER), session_id=SESSION),
            target=TargetRef(kind="item", item_id=ITEM_ID),
            payload={"target_status": "implementing"},
        )
    )
    assert outcome.primary_success is True, outcome.error
    # Real persistence, not a test-authored UPDATE standing in for one.
    assert _status(test_db) == "implementing"

    # The rework adds a new commit to the SAME branch (unlanded again).
    _git(repo, "checkout", "-q", BRANCH)
    (repo / "feature.py").write_text("fixed\n")
    _git(repo, "add", "feature.py")
    _git(repo, "commit", "-q", "-m", "rework after failed release QA")
    b_commit = _git(repo, "rev-parse", BRANCH)

    # This item's own next merge attempt is not foreign or stale work.
    assert landed.stale_unlanded_work(
        item_id=ITEM_ID, branch=BRANCH, target=TARGET, repo_root=str(repo),
        recorded_head="", stale_mismatch_is_foreign=False,
    ) == ""
    assert _lane(ITEM_ID, repo) is None  # the stale receipt no longer answers

    # --- Merge B lands; B gets its own run at its own candidate ---
    _git(repo, "checkout", "-q", TARGET)
    _git(repo, "merge", "-q", "--no-ff", "-m", "merge B", BRANCH)
    b_merge_sha = _git(repo, "rev-parse", TARGET)
    receipt_doc.record_entry(
        test_db, item_id=ITEM_ID, branch=BRANCH, target=TARGET,
        commit_sha=b_commit, merge_sha=b_merge_sha, touched_files=["feature.py"],
    )
    _release_run_awaiting_verdict(test_db, "run-b", LINEAGE_B, "rework-release-b")

    lane_b = _lane(ITEM_ID, repo)
    assert lane_b is not None
    assert (lane_b.commit_sha, lane_b.merge_sha) == (b_commit, b_merge_sha)
    assert _git(repo, "merge-base", "--is-ancestor", a_commit, TARGET) == ""
    assert _git(repo, "merge-base", "--is-ancestor", a_merge_sha, TARGET) == ""

    # B's own pinned identity, and A's observed evidence untouched by it.
    runs = {
        str(row["id"]): (str(row["release_lineage"]), str(row["status"]))
        for row in test_db.execute(
            "SELECT id,release_lineage,status FROM deployment_runs "
            "WHERE id IN ('run-a','run-b')"
        ).fetchall()
    }
    assert runs["run-a"] == (LINEAGE_A, "cancelled")
    assert runs["run-b"] == (LINEAGE_B, "executing")
    after = test_db.execute(
        "SELECT id,observed_release_lineage,status FROM deployment_stage_receipts "
        "WHERE run_id='run-a'"
    ).fetchone()
    assert (
        int(after["id"]),
        str(after["observed_release_lineage"]),
        str(after["status"]),
    ) == (
        int(receipt_a["id"]),
        str(receipt_a["observed_release_lineage"]),
        str(receipt_a["status"]),
    )
    # A's rejection stays readable; it is history, not something B erased.
    assert any(
        "was rejected" in reason
        for reason in item_qa_acceptance_blockers(
            test_db, run_id="run-a", item_id=ITEM_ID
        )
    )

    # --- A late callback bound to A cannot advance anything, B included ---
    with pytest.raises(ValueError, match="is not executing stage"):
        allocate_deployment_stage_receipt(
            test_db, run_id="run-a", stage_name="deploy",
            correlation_id="dispatch-a-late", target_kind="persistent_environment",
            executor="test-runner",
        )
    with pytest.raises(ValueError, match="not belong to the authorized run"):
        complete_deployment_stage_receipt(
            test_db, run_id="run-b", receipt_id=int(receipt_a["id"]),
            correlation_id="dispatch-a-late", status="ready", target_name="stage",
            observed_url="https://preview.example.test",
            observed_release_lineage=LINEAGE_A,
            executor_receipt="executor://dispatch-a-late",
        )
    assert str(
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id='run-b'"
        ).fetchone()["status"]
    ) == "executing"
    assert _status(test_db) == "implementing"
