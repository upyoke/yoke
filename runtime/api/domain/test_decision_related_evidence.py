"""Decision cards receive screenshot evidence from their exact QA subject."""

from __future__ import annotations

import json

from runtime.api.domain.qa_review_seed import _seed_undetermined_review
from yoke_core.domain.decision_related_evidence import related_screenshot_evidence


def test_item_evidence_reports_revision_and_staleness(test_db) -> None:
    seeded = _seed_undetermined_review(
        test_db,
        item_id=4911,
        plan_slug="approval-card-proof",
        decider_roles=("owner",),
    )
    test_db.execute(
        "UPDATE qa_runs SET raw_result=%s WHERE id=%s",
        (
            json.dumps({"verification_tree": {"head_sha": "a" * 40}}),
            seeded["run_id"],
        ),
    )
    test_db.execute(
        "UPDATE qa_artifacts SET content_type='image/png' WHERE id=%s",
        (seeded["artifact_id"],),
    )
    test_db.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
        "raw_result, created_at) VALUES (%s, 'agent', 'review', "
        "'undetermined', 'A person must judge the capture.', %s, "
        "'2026-07-27T00:00:00Z')",
        (
            seeded["requirement_id"],
            json.dumps(
                {
                    "capture_run_id": seeded["run_id"],
                    "verification_tree": {"head_sha": "a" * 40},
                }
            ),
        ),
    )

    current = related_screenshot_evidence(
        test_db,
        item_id=4911,
        expected_revision="a" * 40,
    )
    stale = related_screenshot_evidence(
        test_db,
        item_id=4911,
        expected_revision="b" * 40,
    )

    assert current["state"] == "attached"
    assert current["screenshot_count"] == 1
    assert current["screenshots"][0]["artifact_id"] == seeded["artifact_id"]
    assert current["screenshots"][0]["code_revision"] == "a" * 40
    assert stale["state"] == "stale"


def test_unrelated_and_non_screenshot_artifacts_are_not_shown(test_db) -> None:
    seeded = _seed_undetermined_review(
        test_db,
        item_id=4912,
        plan_slug="approval-card-no-image",
        decider_roles=("owner",),
    )
    test_db.execute(
        "UPDATE qa_artifacts SET artifact_type='terminal_text_capture', "
        "content_type='text/plain' WHERE id=%s",
        (seeded["artifact_id"],),
    )

    result = related_screenshot_evidence(test_db, item_id=4912)
    unrelated = related_screenshot_evidence(test_db, item_id=4913)

    assert result["state"] == "missing"
    assert result["requirement_count"] == 1
    assert result["screenshots"] == []
    assert unrelated["state"] == "absent"
