"""A ready pull request is enqueued directly; arming alone never queues it."""

from __future__ import annotations

from dataclasses import replace
from types import SimpleNamespace

import pytest
from yoke_contracts.timestamps import parse_instant

from runtime.api.merge_queue_landing_test_helpers import (
    ARMED,
    LANE_SHA,
    UNARMED,
    land,
    wire_happy_path,
)
from yoke_core.domain import merge_github_queue as queue_mod
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain.gh_rest_transport_models import RestResponse
from yoke_core.domain.merge_context import MergeArgs, MergeContext
from yoke_core.domain.merge_github_queue import QueueEntryResult

HEAD = "a" * 40


def _ctx() -> MergeContext:
    return MergeContext(args=MergeArgs(branch="YOK-100"), project="yoke")


def _github(monkeypatch, *, mergeable_state, reply=None):
    """Fake one PR read plus one GraphQL mutation; return the mutations sent."""
    monkeypatch.setattr(
        queue_mod,
        "resolve_auth",
        lambda *_a, **_kw: SimpleNamespace(token="tok", repo="upyoke/yoke"),
    )
    sent: list[dict] = []

    def fake_request(req, *, token, **_kw):
        if req.method == "GET":
            body = {"node_id": "PR_node1", "mergeable_state": mergeable_state}
            return RestResponse(status=200, headers={}, body=body)
        sent.append(req.body)
        return RestResponse(status=200, headers={}, body=reply or {"data": {}})

    monkeypatch.setattr(queue_mod, "request_with_retry", fake_request)
    return sent


@pytest.mark.parametrize("mergeable_state", ["clean", "has_hooks", "unstable"])
def test_a_ready_pull_request_is_enqueued_with_its_lane_head(
    monkeypatch, mergeable_state
):
    sent = _github(monkeypatch, mergeable_state=mergeable_state)
    result = queue_mod.enter_merge_queue(_ctx(), "7", expected_head_sha=HEAD)
    assert result.success
    assert "enqueuePullRequest" in sent[0]["query"]
    assert sent[0]["variables"] == {"pullRequestId": "PR_node1", "expectedHeadOid": HEAD}


@pytest.mark.parametrize("mergeable_state", ["blocked", "unknown", "behind", ""])
def test_a_pull_request_still_waiting_is_armed(monkeypatch, mergeable_state):
    sent = _github(monkeypatch, mergeable_state=mergeable_state)
    assert queue_mod.enter_merge_queue(_ctx(), "7", expected_head_sha=HEAD).success
    assert "enablePullRequestAutoMerge" in sent[0]["query"]


def test_an_already_queued_refusal_means_github_holds_the_entry(monkeypatch):
    refusal = {"errors": [{"message": "Pull request is already queued to merge"}]}
    _github(monkeypatch, mergeable_state="clean", reply=refusal)
    result = queue_mod.enter_merge_queue(_ctx(), "7", expected_head_sha=HEAD)
    assert result.success
    assert result.error_detail is None


def test_any_other_enqueue_refusal_stays_named(monkeypatch):
    refusal = {"errors": [{"message": "Expected head oid does not match"}]}
    _github(monkeypatch, mergeable_state="clean", reply=refusal)
    result = queue_mod.enter_merge_queue(_ctx(), "7", expected_head_sha=HEAD)
    assert not result.success
    assert result.rejected
    assert "Expected head oid does not match" in result.error_detail


def test_disarming_a_ready_pull_request_never_enqueues_it(monkeypatch):
    sent = _github(monkeypatch, mergeable_state="clean")
    assert queue_mod.leave_merge_queue(_ctx(), "7").success
    assert "disablePullRequestAutoMerge" in sent[0]["query"]


def _pending(monkeypatch):
    monkeypatch.setattr(
        route_mod,
        "mark_landing_pending",
        lambda item_id, pr_num, **_kw: (parse_instant("2026-11-13T00:00:00Z"), ""),
    )


def _record_entries(monkeypatch, result=None):
    entries: list[tuple[str, str]] = []

    def enter(_ctx, pr_num, *, expected_head_sha=""):
        entries.append((pr_num, expected_head_sha))
        return result or QueueEntryResult(success=True, pr_num=pr_num)

    monkeypatch.setattr(route_mod, "enter_merge_queue", enter)
    return entries


def test_a_rerun_of_an_armed_ready_landing_enqueues_it(monkeypatch):
    wire_happy_path(
        monkeypatch, landing_states=[replace(ARMED, merge_state_status="clean")]
    )
    _pending(monkeypatch)
    entries = _record_entries(monkeypatch)
    outcome = land(wait_for_landing=False)
    assert outcome.ok and outcome.landing_pending
    assert entries == [("42", LANE_SHA)]


def test_an_armed_landing_still_awaiting_checks_is_not_re_entered(monkeypatch):
    wire_happy_path(
        monkeypatch, landing_states=[replace(ARMED, merge_state_status="blocked")]
    )
    _pending(monkeypatch)
    entries = _record_entries(monkeypatch)
    assert land(wait_for_landing=False).ok
    assert entries == []


def test_a_refused_enqueue_of_an_armed_ready_landing_is_named(monkeypatch):
    wire_happy_path(
        monkeypatch, landing_states=[replace(ARMED, merge_state_status="clean")]
    )
    monkeypatch.setattr(
        route_mod,
        "mark_landing_pending",
        lambda *_a, **_kw: pytest.fail("a refused enqueue must not mark a handoff"),
    )
    _record_entries(
        monkeypatch,
        QueueEntryResult(success=False, pr_num="42", error_detail="github graphql refused: no"),
    )
    outcome = land(wait_for_landing=False)
    assert not outcome.ok
    assert outcome.error == "github graphql refused: no"


def test_a_first_entry_passes_the_lane_head(monkeypatch):
    wire_happy_path(monkeypatch, landing_states=[UNARMED])
    _pending(monkeypatch)
    entries = _record_entries(monkeypatch)
    assert land(wait_for_landing=False).ok
    assert entries == [("42", LANE_SHA)]
