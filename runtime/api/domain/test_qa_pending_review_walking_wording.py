"""A walking execution's stage wait says its session is still capturing (YOK-5554).

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
        "plan execution exec-1 is walking; its session is still capturing "
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
