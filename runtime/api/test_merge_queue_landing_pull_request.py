"""The item learns its landing pull request the moment one is resolved.

Both routes into a landing — the verification gate that opens the pull
request and the landing that converges on it — reach the same resolver, so
that is where the number is recorded. Recording it there is what lets the
control-plane observer find the landing later without a process waiting:
the number is on the item before anything is waited on, and it survives a
waiter that dies.
"""

from __future__ import annotations

from runtime.api.merge_queue_landing_test_helpers import CHECKOUT, LANE_SHA, ctx

from yoke_core.domain import merge_queue_landing_pull_request as landing_pr_mod


def _resolving(monkeypatch, resolved):
    """Wire the resolver's answer and capture what gets recorded."""
    monkeypatch.setattr(
        landing_pr_mod,
        "_resolve_landing_pull_request",
        lambda _ctx, _ref, lane_head="": resolved,
    )
    recorded: list[tuple[int, str]] = []
    monkeypatch.setattr(
        "yoke_core.domain.merge_queue_landing_pending.record_landing_pull_request",
        lambda item_id, pr_number: recorded.append((item_id, pr_number)) or "",
    )
    return recorded


def test_a_resolved_pull_request_is_recorded_on_the_item(monkeypatch):
    recorded = _resolving(monkeypatch, ("42", None))

    assert landing_pr_mod.ensure_landing_pull_request(
        ctx(repo_root=CHECKOUT), "YOK-200", lane_head=LANE_SHA, item_id=7
    ) == ("42", None)
    assert recorded == [(7, "42")]


def test_a_caller_with_no_item_in_hand_records_nothing(monkeypatch):
    """The operator-debug path lands a branch without an item to mark."""
    recorded = _resolving(monkeypatch, ("42", None))

    assert landing_pr_mod.ensure_landing_pull_request(
        ctx(repo_root=CHECKOUT), "YOK-200", lane_head=LANE_SHA
    ) == ("42", None)
    assert recorded == []


def test_a_resolver_that_found_nothing_records_nothing(monkeypatch):
    recorded = _resolving(monkeypatch, ("", "no pull request and no commits"))

    landing_pr_mod.ensure_landing_pull_request(
        ctx(repo_root=CHECKOUT), "YOK-200", lane_head=LANE_SHA, item_id=7
    )

    assert recorded == []


def test_a_failed_marker_write_does_not_fail_the_landing(monkeypatch):
    """The merge is the durable fact; the marker is bookkeeping for later."""
    monkeypatch.setattr(
        landing_pr_mod,
        "_resolve_landing_pull_request",
        lambda _ctx, _ref, lane_head="": ("42", None),
    )
    monkeypatch.setattr(
        "yoke_core.domain.merge_queue_landing_pending.record_landing_pull_request",
        lambda item_id, pr_number: "landing pull request record failed",
    )

    assert landing_pr_mod.ensure_landing_pull_request(
        ctx(repo_root=CHECKOUT), "YOK-200", lane_head=LANE_SHA, item_id=7
    ) == ("42", None)
