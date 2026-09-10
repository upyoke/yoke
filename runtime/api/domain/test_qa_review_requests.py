"""QA evidence review requests drive the canonical verdict state."""

from __future__ import annotations

import json

from yoke_core.domain.approval_policy import ApprovalPolicy
from yoke_core.domain.decision_request_resolution import (
    resolve_decision_request,
)
from yoke_core.domain.decision_requests import list_subject_requests
from yoke_core.domain.qa_review_requests import (
    ensure_qa_review_request,
    requirement_awaits_human_review,
)
from runtime.api.domain.qa_review_seed import _seed_undetermined_review


def test_undetermined_review_request_resolves_to_human_verdict(test_db):
    seeded = _seed_undetermined_review(
        test_db,
        item_id=9501,
        plan_slug="review-proof",
        decider_roles=("owner",),
    )
    originator = seeded["originator"]
    owner = seeded["deciders"][0]
    plan_id = seeded["plan_id"]
    requirement_id = seeded["requirement_id"]
    run_id = seeded["run_id"]
    artifact_id = seeded["artifact_id"]

    request, created = ensure_qa_review_request(
        test_db,
        requirement_id=int(requirement_id),
        run_id=int(run_id),
        originator_actor_id=int(originator),
    )
    assert created is True
    assert request is not None
    item_ref = test_db.execute(
        "SELECT p.public_item_prefix || '-' || i.project_sequence "
        "FROM items i JOIN projects p ON p.id = i.project_id WHERE i.id = %s",
        (9501,),
    ).fetchone()[0]
    assert request["subject_context"] == {
        "requirement_id": int(requirement_id),
        "run_id": int(run_id),
        "plan_id": int(plan_id),
        # What the review is a review OF. An item's verification and a
        # deployment run's post-release check are different decisions, and a
        # reviewer told neither cannot tell which one they are answering.
        "subject": {
            "kind": "item",
            "item_id": 9501,
            "item_ref": item_ref,
            "item_title": "Review QA evidence",
            "deployment_run_id": None,
            "target_environment": None,
            "qa_phase": "verification",
        },
        # This run recorded no code identity, so the card says so rather than
        # implying the evidence describes the current tree.
        "code_revision": None,
        "qa_kind": "plan_case",
        "plan_name": "Review proof",
        "case_name": "checkout-flow",
        "method_name": "Browser inspection",
        "title": "QA evidence needs your review",
        "expected_outcome": "The saved state is visible.",
        "verdict_reason": "The screenshot does not show the saved state.",
        "artifacts": [
            {
                "artifact_id": int(artifact_id),
                "artifact_type": "screenshot",
                "content_type": None,
                # The handle rides along so a gate card can label the file and
                # say up front that these bytes only exist on the machine that
                # captured them, exactly as QA detail does.
                "artifact_handle": '{"backend":"local","path":"/tmp/review.png"}',
                # The capture's own caption material — route, step, viewport.
                # This run recorded none, so the reader gets no caption
                # rather than an invented one.
                "metadata": {},
            }
        ],
        "artifact_count": 1,
        "evidence_state": "attached",
        "evidence_summary": "1 attached artifact(s): screenshot",
    }
    waiting = requirement_awaits_human_review(test_db, int(requirement_id))
    assert waiting is not None
    assert waiting.request_id == int(request["id"])
    assert waiting.authorities == ("project operator", "project owner")
    assert "awaits human evidence review" in waiting.detail
    assert f"resolve {request['id']} approve|reject|waive" in waiting.recovery
    resolve_decision_request(
        test_db,
        int(request["id"]),
        actor_id=int(owner),
        action="approve",
        note="Evidence demonstrates the expected behavior.",
    )
    verdicts = test_db.execute(
        "SELECT performed_by, verdict FROM qa_runs "
        "WHERE qa_requirement_id=%s ORDER BY id",
        (requirement_id,),
    ).fetchall()
    assert [(row[0], row[1]) for row in verdicts] == [
        ("agent", "undetermined"),
        ("human_review", "pass"),
    ]
    assert requirement_awaits_human_review(test_db, int(requirement_id)) is None

    empty_run_id = test_db.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
        "started_at, completed_at, created_at) VALUES "
        "(%s, 'agent', 'manual_acceptance', 'undetermined', "
        "'The attempt ended before producing reviewable proof.', "
        "'2026-07-26T00:01:00Z', '2026-07-26T00:01:00Z', "
        "'2026-07-26T00:01:00Z') RETURNING id",
        (requirement_id,),
    ).fetchone()[0]
    empty_request, empty_created = ensure_qa_review_request(
        test_db,
        requirement_id=int(requirement_id),
        run_id=int(empty_run_id),
        originator_actor_id=int(originator),
    )
    assert empty_created is True
    assert empty_request is not None
    assert empty_request["subject_context"]["artifacts"] == []
    assert empty_request["subject_context"]["artifact_count"] == 0
    assert empty_request["subject_context"]["evidence_state"] == "missing"
    assert empty_request["subject_context"]["evidence_summary"] == (
        "No evidence artifacts are attached to this run."
    )


def test_all_mode_review_holds_the_qa_verdict_until_every_box_decides(test_db):
    seeded = _seed_undetermined_review(
        test_db,
        item_id=9502,
        plan_slug="review-proof-all",
        decider_roles=("owner", "operator"),
    )
    requirement_id = seeded["requirement_id"]
    first_decider, second_decider = seeded["deciders"]

    request, created = ensure_qa_review_request(
        test_db,
        requirement_id=requirement_id,
        run_id=seeded["run_id"],
        policy=ApprovalPolicy(roles=("operator", "owner"), mode="all"),
        originator_actor_id=seeded["originator"],
    )
    assert created is True
    assert request is not None

    partial = resolve_decision_request(
        test_db,
        int(request["id"]),
        actor_id=first_decider,
        action="approve",
        note="Owner reviewed the evidence.",
    )
    assert partial["status"] == "pending"
    assert partial["approval_progress"]["satisfied"] == 1
    assert partial["approval_progress"]["required"] == 2
    assert requirement_awaits_human_review(test_db, requirement_id) is not None
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_runs "
            "WHERE qa_requirement_id=%s AND performed_by='human_review'",
            (requirement_id,),
        ).fetchone()[0]
        == 0
    )

    finished = resolve_decision_request(
        test_db,
        int(request["id"]),
        actor_id=second_decider,
        action="approve",
        note="Operator reviewed the evidence.",
    )
    assert finished["status"] == "resolved"
    assert finished["resolution_action"] == "approve"
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs "
            "WHERE qa_requirement_id=%s AND performed_by='human_review'",
            (requirement_id,),
        ).fetchone()[0]
        == "pass"
    )
    assert requirement_awaits_human_review(test_db, requirement_id) is None


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
        }
    ]


def test_pending_review_request_reads_evidence_recorded_after_creation(test_db):
    """Already-pending requests re-resolve evidence on read; resolved ones
    stay frozen at what was actually decided."""
    seeded = _seed_undetermined_review(
        test_db,
        item_id=9506,
        plan_slug="review-proof-live-read",
        decider_roles=("owner",),
    )
    requirement_id = seeded["requirement_id"]
    run_id = test_db.execute(
        "INSERT INTO qa_runs "
        "(qa_requirement_id, performed_by, qa_kind, verdict, verdict_reason, "
        "started_at, completed_at, created_at) VALUES "
        "(%s, 'agent', 'manual_acceptance', 'undetermined', "
        "'The attempt ended before producing reviewable proof.', "
        "'2026-07-26T00:04:00Z', '2026-07-26T00:04:00Z', "
        "'2026-07-26T00:04:00Z') RETURNING id",
        (requirement_id,),
    ).fetchone()[0]
    test_db.commit()

    request, created = ensure_qa_review_request(
        test_db,
        requirement_id=int(requirement_id),
        run_id=int(run_id),
        originator_actor_id=int(seeded["originator"]),
    )
    assert created is True
    assert request["subject_context"]["evidence_state"] == "missing"

    later_artifact_id = test_db.execute(
        "INSERT INTO qa_artifacts "
        "(qa_run_id, artifact_type, artifact_handle, created_at) "
        "VALUES (%s, 'screenshot', %s, '2026-07-26T00:05:00Z') RETURNING id",
        (run_id, '{"backend":"local","path":"/tmp/later.png"}'),
    ).fetchone()[0]
    test_db.commit()

    [live_request] = list_subject_requests(
        test_db, "qa_requirement", str(int(requirement_id))
    )
    assert live_request["subject_context"]["evidence_state"] == "attached"
    assert live_request["subject_context"]["artifact_count"] == 1
    assert live_request["subject_context"]["artifacts"][0]["artifact_id"] == int(
        later_artifact_id
    )
    # The original frozen snapshot on the stored row is untouched.
    assert request["subject_context"]["evidence_state"] == "missing"

    resolve_decision_request(
        test_db,
        int(request["id"]),
        actor_id=int(seeded["deciders"][0]),
        action="approve",
        note="Evidence recorded after the request opened.",
    )
    [resolved_request] = list_subject_requests(
        test_db, "qa_requirement", str(int(requirement_id))
    )
    assert resolved_request["subject_context"]["evidence_state"] == "missing"
