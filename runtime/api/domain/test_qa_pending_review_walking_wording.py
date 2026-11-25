"""A walking execution's stage wait says the walker is still capturing (YOK-5554).

The old line read "walking with pending review bundle", as if capture were
done; for a walk the bundle is the mission's work order.
"""

from __future__ import annotations

from yoke_core.domain.qa_pending_agent_review import (
    PendingAgentReview,
    stage_review_pending_blocker,
)


def test_walking_wait_names_the_work_order_and_ongoing_capture():
    line = stage_review_pending_blocker(
        PendingAgentReview("exec-1", "bundle-9", "walker", state="walking")
    )
    assert (
        "plan execution exec-1 is walking; the walker is still capturing "
        "against mission work order bundle-9"
    ) in line
    assert "pending review bundle" not in line


def test_awaiting_review_wait_still_names_the_pending_review_bundle():
    line = stage_review_pending_blocker(
        PendingAgentReview("exec-1", "bundle-9", "walker")
    )
    assert (
        "plan execution exec-1 is awaiting_walk_review with pending review "
        "bundle bundle-9"
    ) in line


def test_abandoned_walk_names_abort_in_stage_and_capture_blockers():
    from yoke_core.domain.qa_pending_agent_review import capture_verdict_refusal

    pending = PendingAgentReview(
        "exec-1", "bundle-9", "walker", state="walking",
        scope_flag="--item QA-1", owner_ended=True,
    )
    for line in (stage_review_pending_blocker(pending), capture_verdict_refusal(pending, 3)):
        assert "owner has ended" in line
        assert "yoke qa plan abort --item QA-1 --execution-id exec-1" in line
        assert "still capturing" not in line


def test_roster_detects_the_ended_owner_of_a_pending_capture(test_db):
    from runtime.api.domain.deployment_qa_stage_wake_delivery_test_support import (
        _project,
        seed_session,
    )
    from runtime.api.domain.qa_capture_pending_review_test_support import _seed_pending
    from yoke_core.domain.qa_pending_agent_review import pending_review_for_requirement

    _project(test_db)
    seed_session(test_db, "capture-session")
    execution, _, requirement = _seed_pending(test_db, "abandoned-review-owner", "item")
    test_db.execute(
        "UPDATE harness_sessions SET ended_at=last_heartbeat WHERE session_id=%s",
        ("capture-session",),
    )
    test_db.commit()

    pending = pending_review_for_requirement(test_db, requirement)

    assert pending is not None and pending.abandoned_walk
    assert f"yoke qa plan abort --execution-id {execution['id']}" in pending.next_action()
