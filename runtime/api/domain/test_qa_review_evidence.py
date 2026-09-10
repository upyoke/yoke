"""qa_review_artifact_context must not leak a foreign run's evidence.

A reviewed run and the requirement it is reviewed against must actually be
linked in ``qa_runs`` before the resolver walks the capture-link chain --
otherwise a mismatched (requirement_id, run_id) pairing falls through
``qa_evidence_run_id``'s own fallback (which just returns the given run_id)
and the artifact lookup surfaces that foreign run's evidence instead of
refusing.
"""

from __future__ import annotations

from yoke_core.domain.decision_requests import (
    RoleAuthority,
    create_decision_request,
    list_subject_requests,
)
from yoke_core.domain.qa_review_evidence import qa_review_artifact_context
from runtime.api.domain.qa_review_seed import _seed_undetermined_review


def test_run_not_belonging_to_requirement_returns_empty(test_db):
    """requirementA + a genuinely foreign runB (no capture link at all) must
    not surface runB's own artifacts as requirementA's evidence."""
    seeded_a = _seed_undetermined_review(
        test_db, item_id=9507, plan_slug="review-proof-guard-a", decider_roles=("owner",)
    )
    seeded_b = _seed_undetermined_review(
        test_db, item_id=9508, plan_slug="review-proof-guard-b", decider_roles=("owner",)
    )

    result = qa_review_artifact_context(
        test_db,
        requirement_id=int(seeded_a["requirement_id"]),
        run_id=int(seeded_b["run_id"]),
    )
    assert result == {
        "artifacts": [],
        "artifact_count": 0,
        "evidence_state": "missing",
        "evidence_summary": "No evidence artifacts are attached to this run.",
    }


def test_pending_read_rejects_mismatched_requirement_run_pairing(test_db):
    """The pending-read live recompute shares the same guard: a decision
    request whose frozen subject names one requirement but another
    requirement's run must not read back that other requirement's evidence."""
    seeded_a = _seed_undetermined_review(
        test_db, item_id=9509, plan_slug="review-proof-guard-c", decider_roles=("owner",)
    )
    seeded_b = _seed_undetermined_review(
        test_db, item_id=9510, plan_slug="review-proof-guard-d", decider_roles=("owner",)
    )
    project_id = test_db.execute(
        "SELECT project_id FROM qa_requirements WHERE id=%s",
        (seeded_a["requirement_id"],),
    ).fetchone()[0]

    request, created = create_decision_request(
        test_db,
        kind="qa_needs_review",
        subject_type="qa_requirement",
        subject_key=str(int(seeded_a["requirement_id"])),
        project_id=int(project_id),
        originator_actor_id=int(seeded_a["originator"]),
        role_authorities=[RoleAuthority("project", int(project_id), "owner")],
        subject_context={
            "requirement_id": int(seeded_a["requirement_id"]),
            # Mismatched on purpose: this run belongs to seeded_b, not
            # seeded_a. Schema validation only checks shape, not the
            # requirement/run relationship, so this simulates any path that
            # could produce the mismatch the resolver must reject.
            "run_id": int(seeded_b["run_id"]),
            "subject": {
                "kind": "item",
                "item_id": 9509,
                "item_ref": "guard-c",
                "item_title": "Review QA evidence",
                "deployment_run_id": None,
                "target_environment": None,
                "qa_phase": "verification",
            },
            "code_revision": None,
            "expected_outcome": "The saved state is visible.",
            "verdict_reason": "The screenshot does not show the saved state.",
            "artifacts": [],
            "artifact_count": 0,
            "evidence_state": "missing",
            "evidence_summary": "No evidence artifacts are attached to this run.",
        },
    )
    assert created is True

    [live_request] = list_subject_requests(
        test_db, "qa_requirement", str(int(seeded_a["requirement_id"]))
    )
    assert live_request["id"] == request["id"]
    assert live_request["subject_context"]["artifacts"] == []
    assert live_request["subject_context"]["artifact_count"] == 0
    assert live_request["subject_context"]["evidence_state"] == "missing"
