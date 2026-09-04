"""Queue admission exits after its durable handoff unless waiting is explicit."""

from runtime.api.merge_queue_landing_test_helpers import (
    ARMED,
    CHECKOUT,
    LANE_SHA,
    UNARMED,
    ctx,
    land,
    wire_happy_path,
)
from yoke_core.domain import merge_queue_landing_outcome as outcome_mod
from yoke_core.domain import merge_queue_landing_pull_request as landing_pr_mod
from yoke_core.domain import merge_queue_route as route_mod
from yoke_core.domain import qa_case_ci_lane
from yoke_core.domain.qa_case_execution import QaCaseExecutionError


def test_enqueue_records_marker_and_exits_before_poll_or_close_out(monkeypatch):
    wire_happy_path(monkeypatch, landing_states=[UNARMED])
    monkeypatch.setattr(
        route_mod,
        "mark_landing_pending",
        lambda item_id, pr_num, **_kw: ("2026-08-27T18:00:00Z", ""),
    )
    monkeypatch.setattr(
        outcome_mod,
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
    assert "landing_pending=true" in announced[0]
    assert "only when the watcher selected a verified" in announced[0]
    assert "background-wake route" in announced[0]
    assert "reachability-routed watcher with --wait" in announced[0]
    assert "until the landing-complete notification" not in announced[0]


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


def _pending_retry(monkeypatch, *, remote_sha, push):
    wire_happy_path(monkeypatch, landing_states=[ARMED])
    monkeypatch.setattr(landing_pr_mod.git, "remote_head_of", lambda *_a: remote_sha)
    monkeypatch.setattr(qa_case_ci_lane, "push_lane", push)
    monkeypatch.setattr(
        route_mod,
        "mark_landing_pending",
        lambda item_id, pr_num, **_kw: ("2026-09-01T00:00:00Z", ""),
    )
    monkeypatch.setattr(
        route_mod,
        "enter_merge_queue",
        lambda *_a, **_kw: (_ for _ in ()).throw(
            AssertionError("an already-armed PR must not be re-armed")
        ),
    )
    return land(ctx=ctx(repo_root=CHECKOUT), wait_for_landing=False)


def test_pending_retry_pushes_new_commits_before_reporting_ok(monkeypatch):
    """ok:true names the SHA origin holds, which the queue will build."""
    stale = "f" * 40
    pushed: dict = {}

    def push(checkout, branch, *, source_ref="HEAD"):
        pushed.update(checkout=str(checkout), branch=branch, source_ref=source_ref)

    outcome = _pending_retry(monkeypatch, remote_sha=stale, push=push)

    assert outcome.ok
    assert outcome.landing_pending
    assert outcome.commit_sha == LANE_SHA
    assert pushed == {
        "checkout": CHECKOUT,
        "branch": "YOK-200",
        "source_ref": LANE_SHA,
    }


def test_pending_retry_refuses_when_the_new_head_cannot_be_published(
    monkeypatch,
):
    stale = "f" * 40

    def failing_push(*_a, **_kw):
        raise QaCaseExecutionError("permission denied")

    outcome = _pending_retry(monkeypatch, remote_sha=stale, push=failing_push)

    assert not outcome.ok
    assert not outcome.landing_pending
    assert stale in outcome.error
    assert LANE_SHA in outcome.error
    assert "unpublished local commits" in outcome.error
    assert f"{LANE_SHA}:refs/heads/YOK-200" in outcome.error
