"""Browser completion proof follows delivered code while lane proof follows edits."""

from __future__ import annotations

import json
import subprocess

import pytest

from runtime.api.domain.qa_gates_reviewed_impl_test_support import (
    add_requirement,
)
from runtime.api.fixtures.backlog_inserts import (
    insert_deployment_run,
    insert_item,
    insert_item_worktree,
    insert_qa_run,
)
from yoke_core.domain import qa_gate_helpers as helpers
from yoke_core.domain.qa_artifact_handle import local_handle, serialize_handle
from yoke_core.domain.qa_gates import (
    GateTarget,
    check_done_gate,
    check_verification_gate,
)

ITEM_ID = 8941
FLOW = "browser-completion"
RUN_ID = "run-browser-completion"


def _git(repo, *args):
    return subprocess.check_output(
        ["git", "-C", str(repo), *args], text=True, stderr=subprocess.PIPE
    ).strip()


@pytest.fixture
def lane(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-b", "main")
    _git(repo, "config", "user.email", "test@example.test")
    _git(repo, "config", "user.name", "Test")
    (repo / "item.txt").write_text("shipped item code")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Item code")
    shipped = _git(repo, "rev-parse", "HEAD")
    _git(repo, "branch", "item-lane")
    (repo / "other.txt").write_text("other item code")
    _git(repo, "add", ".")
    _git(repo, "commit", "-m", "Other item")
    _git(repo, "checkout", "item-lane")
    _git(repo, "merge", "--ff-only", "main")
    monkeypatch.setattr(helpers, "checkout_for_project", lambda *_: repo)
    return repo, shipped


def _proof(conn, lane, *, captured_sha=None, performed_by="browser_substrate"):
    repo, shipped = lane
    insert_item(conn, id=ITEM_ID, workflow_id="dash", deployment_flow=FLOW)
    insert_item_worktree(conn, item_id=ITEM_ID, branch="item-lane", path=str(repo))
    db_path = str(conn.info.dsn)
    requirement = add_requirement(
        db_path, item_id=ITEM_ID, qa_kind="plan_case", method_id="browser-check"
    )
    run = insert_qa_run(
        conn,
        qa_requirement_id=requirement,
        verdict="pass",
        qa_kind="plan_case",
        performed_by=performed_by,
        raw_result=(
            json.dumps({"code_identity": {"sha": captured_sha or shipped}})
            if performed_by == "browser_substrate"
            else "{}"
        ),
    )
    screenshot = repo / "capture.png"
    screenshot.write_bytes(b"PNG")
    conn.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,artifact_handle,created_at) "
        "VALUES (%s,'screenshot',%s,%s)",
        (
            run["id"],
            serialize_handle(local_handle(str(screenshot))),
            "2026-10-01T00:00:00Z",
        ),
    )
    conn.commit()
    return db_path


def _completion(conn, shipped, *, status="succeeded", settling_at=None):
    insert_deployment_run(
        conn,
        id=RUN_ID,
        flow=FLOW,
        status=status,
        release_lineage=shipped,
        settling_at=settling_at,
    )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at) VALUES (%s,%s,%s)",
        (RUN_ID, ITEM_ID, "2026-10-01T00:00:00Z"),
    )
    conn.commit()


@pytest.mark.parametrize(
    "status,settling_at",
    [
        ("succeeded", None),
        ("executing", "2026-10-01T01:00:00Z"),
    ],
)
def test_delivered_or_settling_member_keeps_proof_after_lane_fast_forward(
    test_db,
    lane,
    status,
    settling_at,
):
    db_path = _proof(test_db, lane)
    _completion(test_db, lane[1], status=status, settling_at=settling_at)
    target = GateTarget(item_id=ITEM_ID)
    # The real git reader sees the unrelated main commit, not the captured one.
    assert helpers._git_latest_code_ref(target, db_path).sha != lane[1]
    assert (
        helpers._resolve_latest_code_ref(
            target, db_path, repo_root=str(lane[0]), for_completion=True
        ).sha
        == lane[1]
    )
    result = check_done_gate(target, db_path)
    assert result.passed, result.errors


def test_new_lane_code_after_capture_still_needs_fresh_verification(test_db, lane):
    db_path = _proof(test_db, lane)
    repo, _ = lane
    (repo / "item.txt").write_text("new item code")
    _git(repo, "add", "item.txt")
    _git(repo, "commit", "-m", "New item code")
    result = check_verification_gate(GateTarget(item_id=ITEM_ID), db_path)
    assert not result.passed
    assert "stale passing runs" in "\n".join(result.errors)
    assert _git(repo, "rev-parse", "HEAD") in "\n".join(result.errors)


def test_completion_refuses_capture_older_than_the_delivered_commit(test_db, lane):
    db_path = _proof(test_db, lane)
    _completion(test_db, _git(lane[0], "rev-parse", "HEAD"))
    result = check_done_gate(GateTarget(item_id=ITEM_ID), db_path)
    assert not result.passed
    assert "stale passing runs" in "\n".join(result.errors)


def test_missing_delivered_identity_names_recovery(test_db, lane):
    db_path = _proof(test_db, lane)
    _completion(test_db, "")
    result = check_done_gate(GateTarget(item_id=ITEM_ID), db_path)
    assert not result.passed
    assert "browser_completion_identity_missing" in "\n".join(result.errors)
    assert "recover its release output" in "\n".join(result.errors)


def test_checkout_free_completion_uses_delivered_identity(test_db, lane, monkeypatch):
    db_path = _proof(test_db, lane)
    _completion(
        test_db, lane[1], status="executing", settling_at="2026-10-01T01:00:00Z"
    )
    test_db.execute(
        "UPDATE qa_artifacts SET artifact_handle=%s",
        (
            serialize_handle(
                {"backend": "s3", "bucket": "test-artifacts", "key": "capture.png"}
            ),
        ),
    )
    # No lane commit, CI identity or merge receipt: delivery is the only revision.
    test_db.commit()
    monkeypatch.setattr("yoke_core.domain.qa_gates._resolve_repo_root", lambda: None)
    result = check_done_gate(GateTarget(item_id=ITEM_ID), db_path)
    assert result.passed, result.errors


def test_command_proof_is_not_reclassified_as_a_browser_capture(test_db, lane):
    db_path = _proof(test_db, lane, performed_by="worktree_run")
    _completion(test_db, lane[1])
    result = check_done_gate(GateTarget(item_id=ITEM_ID), db_path)
    assert result.passed, result.errors
