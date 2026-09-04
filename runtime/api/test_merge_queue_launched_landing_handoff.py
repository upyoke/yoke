"""A launched worker arms the landing and closes out on the notice."""

from runtime.api.merge_queue_landing_test_helpers import (
    LANE_SHA,
    MERGED,
    UNARMED,
    dispatch_for,
    land,
    wire_happy_path,
)
from yoke_core.domain import merge_queue_landing_outcome as outcome_mod
from yoke_core.domain import merge_queue_route as route_mod


def test_launched_session_arms_and_returns_even_when_wait_was_asked_for(monkeypatch):
    wire_happy_path(monkeypatch, landing_states=[UNARMED])
    marked: list[tuple[int, str]] = []
    monkeypatch.setattr(
        route_mod,
        "mark_landing_pending",
        lambda item_id, pr_num, **_kw: (
            marked.append((item_id, pr_num)) or ("2026-09-04T20:00:00Z", "")
        ),
    )
    monkeypatch.setattr(
        route_mod,
        "wait_for_queue_landing",
        lambda **_kw: (_ for _ in ()).throw(
            AssertionError("a launched worker must not hold the landing wait")
        ),
    )
    announced: list[str] = []

    outcome = land(wait_for_landing=True, relay_launched=True, emit=announced.append)

    assert outcome.ok
    assert outcome.landing_pending
    assert outcome.pr_num == "42"
    assert outcome.enqueued_at == "2026-09-04T20:00:00Z"
    assert marked == [(1, "42")]
    assert "landing_pending=true" in announced[0]
    assert "waiting on landing" in announced[0]
    assert "stop deliberately" in announced[0]


def test_reentry_after_the_landing_notice_closes_the_item_out(monkeypatch):
    receipt = wire_happy_path(monkeypatch, landing_states=[MERGED])
    monkeypatch.setattr(
        route_mod,
        "mark_landing_pending",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("a recorded landing re-arms nothing")
        ),
    )
    monkeypatch.setattr(
        outcome_mod,
        "record_landing",
        lambda _ctx, **_kw: _Recorded(receipt),
    )

    outcome = land(
        relay_launched=True,
        dispatch=dispatch_for(
            {"YOK-200": {}},
            merge_queue={"pr_number": "42", "landed_at": "2026-09-04T20:30:00Z"},
        ),
    )

    assert outcome.ok
    assert not outcome.landing_pending
    assert outcome.already_merged
    assert outcome.merge_sha == receipt.merge_sha
    assert outcome.commit_sha == LANE_SHA


class _Recorded:
    """The close-out bookkeeping a landed member owes, already satisfied."""

    def __init__(self, receipt):
        self.batch = receipt
        self.merge_sha = receipt.merge_sha
        self.touched_files = ("a.py",)
        self.warnings = ()

    def ci_evidence_refusal(self, _pr_num, _resume_command):
        return ""
