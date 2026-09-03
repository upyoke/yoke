"""The durable handoff follows GitHub's queue membership, not the arming."""

from runtime.api.merge_queue_landing_test_helpers import (
    UNARMED,
    land,
    wire_happy_path,
)

from yoke_core.domain import merge_queue_route as route_mod


def test_an_unqueued_pull_request_never_reports_a_pending_handoff(monkeypatch):
    """Arming is a request; the durable marker follows GitHub's answer."""
    wire_happy_path(monkeypatch, landing_states=[UNARMED, UNARMED])
    monkeypatch.setattr(
        route_mod,
        "verify_landing_admitted",
        lambda *_a, **_k: (
            "pull request 42 was not taken by the merge queue after the "
            "merge-when-ready request: it conflicts with its base branch"
        ),
    )

    def forbidden(*_a, **_kw):
        raise AssertionError("an unqueued landing must not mark a handoff")

    monkeypatch.setattr(route_mod, "mark_landing_pending", forbidden)

    outcome = land(wait_for_landing=False)

    assert not outcome.ok
    assert outcome.exit_code == route_mod.RECOVERABLE_QUEUE_EXIT_CODE
    assert not outcome.landing_pending
    assert "was not taken by the merge queue" in outcome.error
