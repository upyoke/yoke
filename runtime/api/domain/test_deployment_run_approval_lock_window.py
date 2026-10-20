"""The approval gate holds a run's row lock only for a re-check and its write.

Every read whose cost grows with the run's members happens before the
``deployment_runs`` row lock, so the statements issued after the lock are
the same for a three-member run and a thirty-member run. A change committed
between the unlocked read and the lock is still honoured: the re-check sees
it and the gate decides from a fresh read taken under the lock.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.domain.test_deployment_run_gates import RUN_ID
from runtime.api.domain.test_deployment_run_member_approvals import _mixed_run
from yoke_core.domain import deployment_approval_requests
from yoke_core.domain.deployment_approval_requests import (
    evaluate_deployment_stage_approval,
)

STAGE = "approve-prod"


class OrderedRecorder:
    """Forward every call to ``inner`` while recording statements in order."""

    def __init__(self, inner: Any) -> None:
        self._conn = inner
        self.statements: list[str] = []

    def execute(self, sql: str, *args: Any, **kwargs: Any) -> Any:
        self.statements.append(" ".join(str(sql).split()))
        return self._conn.execute(sql, *args, **kwargs)

    def __getattr__(self, name: str) -> Any:
        return getattr(self._conn, name)

    def after_run_lock(self) -> list[str]:
        """The statements issued once the run row was locked."""
        for index, sql in enumerate(self.statements):
            if "FROM deployment_runs" in sql and "FOR UPDATE" in sql:
                return self.statements[index + 1 :]
        raise AssertionError("the run row was never locked")


def _add_member(
    conn, run_id: str, *, project_id: int, sequence: int, posture: str
) -> int:
    version = int(
        conn.execute(
            "SELECT current_version_id FROM workflows WHERE id='dash'"
        ).fetchone()[0]
    )
    owner = conn.execute("SELECT owner FROM items ORDER BY id LIMIT 1").fetchone()[0]
    item_id = int(
        conn.execute(
            "INSERT INTO items(title,status,priority,created_at,updated_at,source,"
            "owner,project_id,project_sequence,workflow_id,workflow_version_id,"
            "workflow_posture) VALUES (%s,'release','medium',"
            "'2026-09-28T00:00:00Z','2026-09-28T00:00:00Z',%s,%s,%s,%s,"
            "'dash',%s,%s) RETURNING id",
            (
                f"Member {sequence}",
                str(owner),
                str(owner),
                project_id,
                sequence,
                version,
                posture,
            ),
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,delivery_intent,added_at) "
        "VALUES (%s,%s,'final','2026-09-28T00:00:00Z')",
        (run_id, item_id),
    )
    return item_id


APPROVAL_ON_DONE = '{"approval_on_done":true}'


def _run_with_members(
    conn, run_id: str, count: int, *, project_id: int, posture: str
) -> None:
    """Copy the template run and give it *count* members in *posture*."""
    conn.execute(
        "INSERT INTO deployment_runs "
        "(id,project_id,flow,target_tier,target_environment_id,release_lineage,"
        "status,current_stage,created_at) "
        "SELECT %s,project_id,flow,target_tier,target_environment_id,"
        "release_lineage,status,current_stage,created_at "
        "FROM deployment_runs WHERE id=%s",
        (run_id, RUN_ID),
    )
    base = int(
        conn.execute(
            "SELECT COALESCE(MAX(project_sequence),0) FROM items WHERE project_id=%s",
            (project_id,),
        ).fetchone()[0]
    )
    for offset in range(1, count + 1):
        _add_member(
            conn,
            run_id,
            project_id=project_id,
            sequence=base + offset,
            posture=posture,
        )
    conn.commit()


def _approve_member_decisions(conn, run_id: str, owner: int) -> None:
    """Open each member's own done decision, then answer it as approved."""
    blocked = evaluate_deployment_stage_approval(conn, run_id=run_id, stage=STAGE)
    assert blocked.request_status == "blocked_member"
    conn.execute(
        "UPDATE decision_requests SET status='resolved',resolution_action='approve',"
        "resolution_actor_id=%s,resolved_at='2026-09-28T00:01:00Z' "
        "WHERE subject_type='item_transition' AND status='pending' AND subject_key "
        "IN (SELECT item_id::text || ':done' FROM deployment_run_items "
        "WHERE run_id=%s)",
        (owner, run_id),
    )
    conn.commit()


def _statements_under_lock(conn, run_id: str) -> list[str]:
    recorder = OrderedRecorder(conn)
    verdict = evaluate_deployment_stage_approval(recorder, run_id=run_id, stage=STAGE)
    assert verdict.request_status == "pending"
    assert verdict.request_id > 0
    return recorder.after_run_lock()


@pytest.mark.parametrize("posture", [APPROVAL_ON_DONE, "{}"])
def test_statements_under_the_run_lock_do_not_grow_with_members(test_db, posture):
    """Members with approved done decisions, and members needing none."""
    _template, _item, owner, platform_id = _mixed_run(test_db)
    for run_id, count in (("run-lock-small", 3), ("run-lock-large", 30)):
        _run_with_members(
            test_db, run_id, count, project_id=platform_id, posture=posture
        )
        if posture == APPROVAL_ON_DONE:
            _approve_member_decisions(test_db, run_id, owner)

    small = _statements_under_lock(test_db, "run-lock-small")
    large = _statements_under_lock(test_db, "run-lock-large")

    assert len(large) == len(small), large
    # Only the one-statement fingerprint re-check reads membership under it.
    membership_reads = [sql for sql in large if "deployment_run_items" in sql]
    assert len(membership_reads) == 1, large
    assert "md5" in membership_reads[0]
    # Evaluating again finds the request: the lock covers only the re-check.
    repeated = OrderedRecorder(test_db)
    evaluate_deployment_stage_approval(repeated, run_id="run-lock-large", stage=STAGE)
    assert len(repeated.after_run_lock()) <= 2


def _commit_before_lock(monkeypatch, conn, change: str, params: tuple) -> None:
    """Commit *change* after the gate's unlocked read, before its run lock."""
    real = deployment_approval_requests._run

    def run_then_change(inner, run_id, *, for_update=False):
        if for_update:
            conn.execute(change, params)
            conn.commit()
        return real(inner, run_id, for_update=for_update)

    monkeypatch.setattr(deployment_approval_requests, "_run", run_then_change)


def test_member_rejection_committed_before_the_lock_is_honoured(test_db, monkeypatch):
    _template, _item, owner, platform_id = _mixed_run(test_db)
    _run_with_members(
        test_db, "run-lock-recheck", 3, project_id=platform_id, posture=APPROVAL_ON_DONE
    )
    _approve_member_decisions(test_db, "run-lock-recheck", owner)
    _commit_before_lock(
        monkeypatch,
        test_db,
        "UPDATE decision_requests SET resolution_action='reject' WHERE id=("
        "SELECT MIN(r.id) FROM decision_requests r JOIN deployment_run_items m "
        "ON r.subject_key=m.item_id::text || ':done' WHERE m.run_id=%s)",
        ("run-lock-recheck",),
    )

    verdict = evaluate_deployment_stage_approval(
        test_db, run_id="run-lock-recheck", stage=STAGE
    )

    assert verdict.request_status == "rejected_member"
    assert "was rejected" in verdict.reason
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM decision_requests WHERE subject_key=%s",
            (f"run-lock-recheck:{STAGE}",),
        ).fetchone()[0]
        == 0
    )


def test_member_added_before_the_lock_reaches_the_request(test_db, monkeypatch):
    _template, _item, owner, platform_id = _mixed_run(test_db)
    _run_with_members(
        test_db, "run-lock-joined", 3, project_id=platform_id, posture=APPROVAL_ON_DONE
    )
    _approve_member_decisions(test_db, "run-lock-joined", owner)
    late = _add_member(
        test_db,
        "run-lock-joined",
        project_id=platform_id,
        sequence=900,
        posture="{}",
    )
    test_db.execute("DELETE FROM deployment_run_items WHERE item_id=%s", (late,))
    test_db.commit()
    _commit_before_lock(
        monkeypatch,
        test_db,
        "INSERT INTO deployment_run_items(run_id,item_id,delivery_intent,added_at) "
        "VALUES (%s,%s,'final','2026-09-28T00:00:00Z')",
        ("run-lock-joined", late),
    )

    verdict = evaluate_deployment_stage_approval(
        test_db, run_id="run-lock-joined", stage=STAGE
    )

    assert verdict.request_status == "pending"
    context = test_db.execute(
        "SELECT subject_context FROM decision_requests WHERE id=%s",
        (verdict.request_id,),
    ).fetchone()[0]
    batch = json.loads(context)["batch"]
    assert batch["item_count"] == 4
    assert late in {item["item_id"] for item in batch["items"]}
