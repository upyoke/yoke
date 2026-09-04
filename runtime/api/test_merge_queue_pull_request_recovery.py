"""A queue landing converges on the pull request that carries its lane head."""

import pytest

from runtime.api.merge_queue_landing_test_helpers import (
    ARMED,
    MERGED,
    UNARMED,
    land,
    landing_record,
    wire_happy_path,
)
from yoke_core.domain import merge_queue_landing_outcome as outcome_mod
from yoke_core.domain import merge_queue_landing_pull_request as landing_pr_mod
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain.merge_queue_close_out import QueueCloseOut
from yoke_core.engines.merge_worktree_pr_queue import QueueEntryResult
from yoke_core.engines.merge_worktree_pr_rest import PrCreateResult


def test_reentry_with_merged_pr_skips_queue_entry(monkeypatch):
    wire_happy_path(monkeypatch)

    def forbidden_entry(_ctx, pr_num):
        raise AssertionError("must not re-enter an already-merged PR")

    monkeypatch.setattr(route_mod, "enter_merge_queue", forbidden_entry)
    outcome = land()
    assert outcome.ok
    assert outcome.already_merged


def test_reentry_with_armed_pr_skips_entry_and_waits_on_the_record(monkeypatch):
    wire_happy_path(monkeypatch, landing_states=[ARMED, MERGED])

    def forbidden_entry(_ctx, pr_num):
        raise AssertionError("must not re-arm merge-when-ready")

    monkeypatch.setattr(route_mod, "enter_merge_queue", forbidden_entry)
    assert land().ok


def test_the_landing_enqueues_the_pull_request_the_gate_opened(monkeypatch):
    """The gate's pull request is armed rather than replaced by a second."""
    wire_happy_path(monkeypatch, landing_states=[UNARMED, MERGED])

    def forbidden(*_a, **_kw):
        raise AssertionError("the gate's pull request must be reused")

    monkeypatch.setattr(landing_pr_mod, "create_pr", forbidden)
    entered: list[str] = []
    monkeypatch.setattr(
        route_mod,
        "enter_merge_queue",
        lambda _ctx, pr_num: entered.append(pr_num) or QueueEntryResult(success=True),
    )

    outcome = land()

    assert outcome.ok
    assert outcome.pr_num == "42"
    assert entered == ["42"]


def test_reentry_after_the_queue_merged_never_opens_a_second_pr(monkeypatch):
    wire_happy_path(monkeypatch)

    def forbidden(*_a, **_kw):
        raise AssertionError("a merged PR must not be recreated or re-entered")

    monkeypatch.setattr(landing_pr_mod, "create_pr", forbidden)
    monkeypatch.setattr(route_mod, "enter_merge_queue", forbidden)
    outcome = land()
    assert outcome.ok
    assert outcome.pr_num == "42"


@pytest.mark.parametrize("refusal", ["already_exists", "no_commits"])
def test_recoverable_create_refusals_rediscover_the_pull_request(
    monkeypatch,
    refusal,
):
    wire_happy_path(monkeypatch)
    found = [(None, None, ""), ("url", "42", "")]
    monkeypatch.setattr(
        landing_pr_mod,
        "find_landable_pull_request",
        lambda _ctx, lane_head="": found.pop(0),
    )
    monkeypatch.setattr(
        landing_pr_mod,
        "create_pr",
        lambda _ctx, **_kw: PrCreateResult(pr_url="", pr_num="", **{refusal: True}),
    )
    outcome = land()
    assert outcome.ok
    assert outcome.pr_num == "42"


def test_lane_beyond_the_merged_pull_request_lands_freshly(monkeypatch):
    """A lane with later commits opens and records its own pull request."""
    wire_happy_path(monkeypatch, landing_states=[UNARMED, MERGED])
    monkeypatch.setattr(
        landing_pr_mod,
        "find_landable_pull_request",
        lambda _ctx, lane_head="": (None, None, "pull request 42 merged head"),
    )
    monkeypatch.setattr(
        landing_pr_mod,
        "create_pr",
        lambda _ctx, **_kw: PrCreateResult(pr_url="https://gh/99", pr_num="99"),
    )
    entered: list[str] = []
    monkeypatch.setattr(
        route_mod,
        "enter_merge_queue",
        lambda _ctx, pr_num: (
            entered.append(pr_num) or QueueEntryResult(success=True, pr_num=pr_num)
        ),
    )
    landed: list[str] = []
    monkeypatch.setattr(
        outcome_mod,
        "record_landing",
        lambda _ctx, **kw: (
            landed.append(kw["pr_num"])
            or QueueCloseOut(merge_sha="n" * 40, touched_files=("a.py",))
        ),
    )

    outcome = land(
        landing_records=[
            landing_record(
                pr_number="99",
                narrative="pull request 99: merged=true",
            )
        ]
    )

    assert outcome.ok
    assert outcome.pr_num == "99"
    assert not outcome.already_merged
    assert entered == ["99"]
    assert landed == ["99"]


def test_lane_beyond_the_merged_pull_request_records_nothing_when_stuck(
    monkeypatch,
):
    wire_happy_path(monkeypatch)
    monkeypatch.setattr(
        landing_pr_mod,
        "find_landable_pull_request",
        lambda _ctx, lane_head="": (
            None,
            None,
            "pull request 42 merged head aaaa, not the lane head bbbb",
        ),
    )
    monkeypatch.setattr(
        landing_pr_mod,
        "create_pr",
        lambda _ctx, **_kw: PrCreateResult(pr_url="", pr_num="", no_commits=True),
    )

    def forbidden(*_a, **_kw):
        raise AssertionError("a refused convergence must record nothing")

    monkeypatch.setattr(outcome_mod, "record_landing", forbidden)

    outcome = land()

    assert not outcome.ok
    assert "carries commits beyond the pull request that merged it" in outcome.error
    assert "not the lane head bbbb" in outcome.error


def test_no_commits_without_any_pull_request_is_named(monkeypatch):
    wire_happy_path(monkeypatch)
    monkeypatch.setattr(
        landing_pr_mod,
        "find_landable_pull_request",
        lambda _ctx, lane_head="": (None, None, ""),
    )
    monkeypatch.setattr(
        landing_pr_mod,
        "create_pr",
        lambda _ctx, **_kw: PrCreateResult(pr_url="", pr_num="", no_commits=True),
    )
    outcome = land()
    assert not outcome.ok
    assert "no commits against" in outcome.error
    assert "YOK-200" in outcome.error
