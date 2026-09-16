"""A reviewed run that names another run's capture as its evidence.

Split from the review-request suite so both files stay under the authored
line limit; these two cover the ``capture_run_id`` link and the refusal
that keeps it from reaching across requirements.
"""

from __future__ import annotations

import json

from yoke_contracts.qa_artifact_read import artifact_read_command
from yoke_core.domain.qa_review_requests import ensure_qa_review_request
from runtime.api.domain.qa_review_seed import _seed_undetermined_review


def test_review_request_resolves_capture_linked_artifacts(test_db):
    """A reviewed run that names its evidence through another run's capture
    reports that capture's artifacts, not an empty set queried straight off
    its own id."""
    seeded = _seed_undetermined_review(
        test_db,
        item_id=9503,
        plan_slug="review-proof-capture-link",
        decider_roles=("owner",),
    )
    requirement_id = seeded["requirement_id"]

    capture_run_id = test_db.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
        "started_at, completed_at, created_at) VALUES "
        "(%s, 'agent', 'manual_acceptance', 'undetermined', 'Recording only.', "
        "'2026-07-26T00:02:00Z', '2026-07-26T00:02:00Z', "
        "'2026-07-26T00:02:00Z') RETURNING id",
        (requirement_id,),
    ).fetchone()[0]
    linked_artifact_id = test_db.execute(
        "INSERT INTO qa_artifacts "
        "(qa_run_id, artifact_type, artifact_handle, created_at) "
        "VALUES (%s, 'screenshot', %s, '2026-07-26T00:02:00Z') RETURNING id",
        (capture_run_id, '{"backend":"local","path":"/tmp/linked.png"}'),
    ).fetchone()[0]
    linked_run_id = test_db.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
        "raw_result, started_at, completed_at, created_at) VALUES "
        "(%s, 'agent', 'manual_acceptance', 'undetermined', "
        "'The screenshot does not show the saved state.', %s, "
        "'2026-07-26T00:03:00Z', '2026-07-26T00:03:00Z', "
        "'2026-07-26T00:03:00Z') RETURNING id",
        (requirement_id, json.dumps({"capture_run_id": capture_run_id})),
    ).fetchone()[0]
    test_db.commit()

    request, created = ensure_qa_review_request(
        test_db,
        requirement_id=int(requirement_id),
        run_id=int(linked_run_id),
        originator_actor_id=int(seeded["originator"]),
    )
    assert created is True
    # The request still names the exact run it reviewed, not the capture.
    assert request["subject_context"]["run_id"] == int(linked_run_id)
    assert request["subject_context"]["evidence_state"] == "attached"
    assert request["subject_context"]["artifact_count"] == 1
    assert request["subject_context"]["artifacts"][0]["artifact_id"] == int(
        linked_artifact_id
    )


def test_review_request_rejects_cross_requirement_capture_link(test_db):
    """A ``capture_run_id`` is untrusted data, not a foreign key -- one
    naming another requirement's run must not leak that subject's evidence."""
    seeded_a = _seed_undetermined_review(
        test_db, item_id=9504, plan_slug="review-proof-a", decider_roles=("owner",)
    )
    seeded_b = _seed_undetermined_review(
        test_db, item_id=9505, plan_slug="review-proof-b", decider_roles=("owner",)
    )
    test_db.execute(
        "UPDATE qa_runs SET raw_result=%s WHERE id=%s",
        (json.dumps({"capture_run_id": seeded_a["run_id"]}), seeded_b["run_id"]),
    )
    test_db.commit()

    request, created = ensure_qa_review_request(
        test_db,
        requirement_id=int(seeded_b["requirement_id"]),
        run_id=int(seeded_b["run_id"]),
        originator_actor_id=int(seeded_b["originator"]),
    )
    assert created is True
    assert request["subject_context"]["artifacts"] == [
        {
            "artifact_id": int(seeded_b["artifact_id"]),
            "artifact_type": "screenshot",
            "content_type": None,
            "artifact_handle": '{"backend":"local","path":"/tmp/review.png"}',
            "metadata": {},
            "read_command": artifact_read_command(
                int(seeded_b["requirement_id"]), int(seeded_b["artifact_id"])
            ),
        }
    ]
