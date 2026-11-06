"""An item's approval shows what its current release captured for it.

A carried item's production QA is recorded as a member requirement of the
release run, not as a requirement on the item. The item's approval must see
that capture, including the capture an accepted independent review points
back to, while checks from an earlier release stay out. The approver's
evidence is refreshed while the request is pending and kept once it resolves.
"""

from __future__ import annotations

from runtime.api.domain.decision_member_release_evidence_test_support import (
    EARLIER_RUN as EARLIER_RUN,
    MEMBER as MEMBER,
    _pending_done_approval as _pending_done_approval,
    _seed_earlier_release as _seed_earlier_release,
)


import json
from typing import Any

from yoke_core.domain.decision_related_evidence import related_screenshot_evidence
from yoke_core.domain.decision_request_resolution import resolve_decision_request
from yoke_core.domain.decision_request_rows import request_row

CURRENT_RUN = "run-20260928-861"


def _screenshot_run(conn: Any, requirement_id: int, created_at: str) -> tuple[int, int]:
    run_id = int(
        conn.execute(
            "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,"
            "execution_status,case_outcome,raw_result,started_at,completed_at,"
            "created_at) VALUES(%s,'browser_substrate','method_case','captured',"
            "'needs_review','{}',%s,%s,%s) RETURNING id",
            (requirement_id, created_at, created_at, created_at),
        ).fetchone()["id"]
    )
    artifact_id = int(
        conn.execute(
            "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
            "artifact_handle,created_at) VALUES(%s,'screenshot','image/png',%s,%s) "
            "RETURNING id",
            (run_id, json.dumps({"backend": "local", "path": "/tmp/s.png"}), created_at),
        ).fetchone()["id"]
    )
    return run_id, artifact_id


def _second_release(conn: Any, earlier_requirement: int) -> int:
    """Carry the same member in a newer run with its own member requirement."""
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,release_lineage,status,"
        "current_stage,created_at,composition_frozen_at,requirement_snapshot) "
        "SELECT %s,project_id,flow,release_lineage,status,current_stage,"
        "'2999-01-01T00:00:00Z',composition_frozen_at,requirement_snapshot "
        "FROM deployment_runs WHERE id=%s",
        (CURRENT_RUN, EARLIER_RUN),
    )
    conn.execute(
        "INSERT INTO deployment_run_items(run_id,item_id,added_at,delivery_intent,"
        "requirement_snapshot) SELECT %s,item_id,added_at,delivery_intent,"
        "requirement_snapshot FROM deployment_run_items "
        "WHERE run_id=%s AND item_id=%s",
        (CURRENT_RUN, EARLIER_RUN, MEMBER),
    )
    row = dict(
        conn.execute(
            "SELECT * FROM qa_requirements WHERE id=%s", (earlier_requirement,)
        ).fetchone()
    )
    row.pop("id")
    row["deployment_run_id"] = CURRENT_RUN
    columns = ", ".join(row)
    markers = ", ".join("%s" for _ in row)
    return int(
        conn.execute(
            f"INSERT INTO qa_requirements ({columns}) VALUES ({markers}) RETURNING id",
            tuple(row.values()),
        ).fetchone()["id"]
    )


def _capture_releases(conn: Any, earlier: int) -> dict[str, int]:
    """Capture in both releases; the current capture passes independent review."""
    _, earlier_shot = _screenshot_run(conn, earlier, "2026-09-01T00:00:00Z")
    current = _second_release(conn, earlier)
    capture_run, current_shot = _screenshot_run(conn, current, "2026-09-28T00:00:00Z")
    # The accepted review records no artifact of its own; it points back to
    # the capture it judged.
    conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "raw_result,created_at) VALUES(%s,'agent','review','pass',%s,"
        "'2026-09-28T00:05:00Z')",
        (current, json.dumps({"capture_run_id": capture_run})),
    )
    conn.commit()
    return {"earlier_shot": earlier_shot, "current_shot": current_shot}


def test_item_evidence_is_its_current_release_member_capture(test_db) -> None:
    seeded = _capture_releases(test_db, _seed_earlier_release(test_db))

    evidence = related_screenshot_evidence(test_db, item_id=MEMBER)

    assert evidence["release_run_id"] == CURRENT_RUN
    assert [shot["artifact_id"] for shot in evidence["screenshots"]] == [
        seeded["current_shot"]
    ]
    assert evidence["state"] == "attached"


def test_item_with_no_capture_reports_missing_not_attached(test_db) -> None:
    requirement = _seed_earlier_release(test_db)

    command_only = related_screenshot_evidence(test_db, item_id=MEMBER)
    test_db.execute(
        "UPDATE qa_requirements SET method_id='browser-inspection' WHERE id=%s",
        (requirement,),
    )
    visual = related_screenshot_evidence(test_db, item_id=MEMBER)

    # A command check never promised a screenshot; a screenshot check did.
    assert command_only["state"] == "not_expected"
    assert visual["state"] == "missing"
    assert visual["screenshots"] == []


def test_pending_approval_reads_live_evidence_and_keeps_it_when_resolved(
    test_db,
) -> None:
    earlier = _seed_earlier_release(test_db)
    request_id = _pending_done_approval(test_db)
    stored = json.loads(
        test_db.execute(
            "SELECT subject_context FROM decision_requests WHERE id=%s", (request_id,)
        ).fetchone()[0]
    )
    assert stored["evidence"]["screenshots"] == []

    seeded = _capture_releases(test_db, earlier)
    pending = request_row(test_db, request_id)
    shots = [s["artifact_id"] for s in pending["subject_context"]["evidence"]["screenshots"]]
    assert shots == [seeded["current_shot"]]

    actor = pending["named_actor_ids"][0]
    resolved = resolve_decision_request(
        test_db, request_id, actor_id=actor, action="approve"
    )
    assert resolved["status"] == "resolved"
    kept = [s["artifact_id"] for s in resolved["subject_context"]["evidence"]["screenshots"]]
    assert kept == [seeded["current_shot"]]
