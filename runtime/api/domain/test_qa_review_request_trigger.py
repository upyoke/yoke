"""Which undetermined verdicts owe a person a decision.

An agent-judged verdict that cannot be called halts the item for owner or
operator review. Which runs count as agent-judged is the whole question here:
Browser and Terminal inspections are judged by an agent and refuse
``performed_by='agent'`` outright, so the requirement's declared
``verdict_path`` answers it and the performer string does not.
"""

from __future__ import annotations

from runtime.api.domain.qa_review_seed import _seed_undetermined_review
from yoke_core.domain.qa_review_requests import (
    maybe_ensure_qa_review_request,
    requirement_awaits_human_review,
)


def test_an_inspection_verdict_reaches_a_person_under_its_own_performer(test_db):
    """A Browser inspection's undetermined verdict still asks for a review.

    Browser and Terminal methods are judged by an agent but refuse
    ``performed_by='agent'`` outright — their runs are recorded under the
    substrate that captured them. Keying the review request on that string
    meant an undetermined inspection verdict raised nothing and reached
    nobody, while the method's own contract promised the item would halt for
    owner or operator review. The requirement's ``verdict_path`` is the fact
    that actually answers it.
    """
    seeded = _seed_undetermined_review(
        test_db,
        item_id=9503,
        plan_slug="inspection-proof",
        decider_roles=("owner",),
        performed_by="browser_substrate",
    )
    request = maybe_ensure_qa_review_request(
        test_db,
        verdict="undetermined",
        requirement_id=int(seeded["requirement_id"]),
        run_id=int(seeded["run_id"]),
        originator_actor_id=int(seeded["originator"]),
    )
    assert request is not None
    assert request["kind"] == "qa_needs_review"
    assert request["status"] == "pending"

    # And the blocking wait names it, so the gate's recovery points at the
    # review rather than reporting an unexplained unsatisfied requirement.
    waiting = requirement_awaits_human_review(test_db, int(seeded["requirement_id"]))
    assert waiting is not None
    assert waiting.request_id == int(request["id"])


def test_an_automatic_verdict_never_asks_for_a_review(test_db):
    """A method whose verdict path is automatic owes no one a decision."""
    seeded = _seed_undetermined_review(
        test_db,
        item_id=9504,
        plan_slug="automatic-proof",
        decider_roles=("owner",),
        performed_by="worktree_run",
    )
    test_db.execute(
        "UPDATE qa_requirements SET verdict_path='automatic' WHERE id=%s",
        (int(seeded["requirement_id"]),),
    )
    test_db.commit()
    assert (
        maybe_ensure_qa_review_request(
            test_db,
            verdict="undetermined",
            requirement_id=int(seeded["requirement_id"]),
            run_id=int(seeded["run_id"]),
            originator_actor_id=int(seeded["originator"]),
        )
        is None
    )
