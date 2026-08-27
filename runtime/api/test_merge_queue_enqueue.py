"""Queue admission exits after its durable handoff unless waiting is explicit."""

from runtime.api.merge_queue_landing_test_helpers import (
    UNARMED,
    land,
    wire_happy_path,
)
from yoke_core.domain import merge_queue_route as route_mod


def test_enqueue_records_marker_and_exits_before_poll_or_close_out(monkeypatch):
    wire_happy_path(monkeypatch, landing_states=[UNARMED])
    monkeypatch.setattr(
        route_mod,
        "mark_landing_pending",
        lambda item_id, pr_num, **_kw: ("2026-08-27T18:00:00Z", ""),
    )
    monkeypatch.setattr(
        route_mod,
        "record_landing",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("enqueue-only mode must not close out")
        ),
    )
    announced: list[str] = []

    outcome = land(wait_for_landing=False, emit=announced.append)

    assert outcome.ok
    assert outcome.landing_pending
    assert outcome.enqueued_at == "2026-08-27T18:00:00Z"
    assert outcome.commit_sha
    assert "in the merge queue" in announced[0]


def test_enqueue_refuses_success_when_the_durable_marker_is_missing(monkeypatch):
    wire_happy_path(monkeypatch, landing_states=[UNARMED])
    monkeypatch.setattr(
        route_mod,
        "mark_landing_pending",
        lambda item_id, pr_num, **_kw: ("", "control plane is behind"),
    )

    outcome = land(wait_for_landing=False)

    assert not outcome.ok
    assert "durable close-out marker was not recorded" in outcome.error
    assert "--wait" in outcome.error
