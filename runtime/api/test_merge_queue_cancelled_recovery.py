"""Real merge route recovery on armed and unarmed exact-head candidates."""

from dataclasses import replace

import pytest

from runtime.api.merge_queue_landing_test_helpers import (
    ARMED,
    UNARMED,
    MERGED,
    CLOSED,
    land,
    wire_happy_path,
)
from runtime.api.domain.test_ci_no_verdict_redispatch import (
    CANCELLED_REQUIRED,
    FAILED_REQUIRED,
    QUEUED_REQUIRED,
    _rerun_fakes,
)
from yoke_core.domain import merge_queue_route as route
from yoke_core.domain import merge_queue_enqueue_verification as admission
from yoke_core.domain import merge_queue_entry_check_redispatch as recovery
from yoke_core.engines.merge_worktree_pr_membership import PrQueueMembership


@pytest.mark.parametrize("started", [False, True])
@pytest.mark.parametrize("armed", [False, True])
@pytest.mark.parametrize("conclusion", ["cancelled", "startup_failure"])
def test_retry_recovers_at_real_route_without_duplicate_arming(
    monkeypatch, armed, conclusion, started
):
    wire_happy_path(monkeypatch, landing_states=[ARMED if armed else UNARMED])
    posts = _rerun_fakes(monkeypatch, started=started)
    checks = [replace(CANCELLED_REQUIRED, conclusion=conclusion)]
    entered = []
    monkeypatch.setattr(
        route,
        "enter_merge_queue",
        lambda *a: entered.append(a) or type("Entry", (), {"success": True})(),
    )

    def read_checks(*a):
        return (tuple(checks), None)

    def sleep(*a):
        checks[:] = [QUEUED_REQUIRED]

    monkeypatch.setattr(
        admission,
        "read_landing",
        lambda *a, **kw: admission.LandingReadback(
            state=ARMED,
            membership=PrQueueMembership(False),
            required_checks=tuple(checks),
        ),
    )
    monkeypatch.setattr(
        route,
        "red_entry_checks_refusal",
        lambda *a, **kw: admission.red_entry_checks_refusal(
            *a, **kw, read_checks=read_checks
        ),
    )
    outcome = land(wait_for_landing=False, sleep=sleep)
    assert outcome.ok and outcome.landing_pending
    assert len(posts) == 1
    assert posts[0][1].endswith("/rerun-failed-jobs" if started else "/rerun")
    assert len(entered) == (0 if armed else 1)


@pytest.mark.parametrize(
    "state,enqueued", [(ARMED, True), (MERGED, False), (CLOSED, False)]
)
def test_active_merged_and_closed_pr_never_rerun(monkeypatch, state, enqueued):
    wire_happy_path(monkeypatch, landing_states=[state])
    posts = _rerun_fakes(monkeypatch)
    monkeypatch.setattr(
        admission,
        "read_landing",
        lambda *a, **kw: admission.LandingReadback(
            state=state,
            membership=PrQueueMembership(enqueued),
            required_checks=(CANCELLED_REQUIRED,),
        ),
    )
    monkeypatch.setattr(
        route,
        "red_entry_checks_refusal",
        lambda *a, **kw: admission.red_entry_checks_refusal(
            *a, **kw, read_checks=lambda *a: ((CANCELLED_REQUIRED,), None)
        ),
    )
    # Closed PRs are rejected by the real ensure-PR boundary, before recovery.
    if state.closed and not state.merged:
        monkeypatch.setattr(
            route,
            "ensure_landing_pull_request",
            lambda *a, **kw: ("", "PR closed; reopen before retry"),
        )
    land(wait_for_landing=False)
    assert posts == []


def test_armed_real_failure_refuses_without_rerun(monkeypatch):
    wire_happy_path(monkeypatch, landing_states=[ARMED])
    posts = _rerun_fakes(monkeypatch)
    monkeypatch.setattr(
        admission,
        "read_landing",
        lambda *a, **kw: admission.LandingReadback(
            state=ARMED,
            membership=PrQueueMembership(False),
            required_checks=(FAILED_REQUIRED,),
        ),
    )
    monkeypatch.setattr(
        route,
        "red_entry_checks_refusal",
        lambda *a, **kw: admission.red_entry_checks_refusal(*a, **kw),
    )
    outcome = land(wait_for_landing=False)
    assert not outcome.ok
    assert "fix it on the lane" in outcome.error
    assert not posts


def test_changed_candidate_refuses_before_post(monkeypatch):
    posts = _rerun_fakes(monkeypatch)
    refusal = recovery.redispatch_no_verdict_checks(
        None, "42", (CANCELLED_REQUIRED,), lane_head="2" * 40
    )
    assert "ci_rerun_stale_head" in refusal
    assert not posts


def test_successful_required_replacement_never_reruns(monkeypatch):
    wire_happy_path(monkeypatch, landing_states=[ARMED])
    posts = _rerun_fakes(monkeypatch)
    monkeypatch.setattr(
        admission,
        "read_landing",
        lambda *a, **kw: admission.LandingReadback(
            state=ARMED,
            membership=PrQueueMembership(False),
            required_checks=(replace(CANCELLED_REQUIRED, conclusion="success"),),
        ),
    )
    monkeypatch.setattr(
        route,
        "red_entry_checks_refusal",
        lambda *a, **kw: admission.red_entry_checks_refusal(*a, **kw),
    )
    assert land(wait_for_landing=False).ok
    assert not posts


@pytest.mark.parametrize(
    "condition,reason",
    [
        ("active", "ci_rerun_not_failed"),
        ("superseded", "ci_rerun_superseded"),
        ("head_changed", "ci_rerun_stale_head"),
        ("job_failed", "ci_rerun_verdict"),
        ("repeated", "ci_rerun_limit"),
    ],
)
def test_armed_route_preserves_authoritative_run_protections(
    monkeypatch, condition, reason
):
    from yoke_core.domain import github_actions_rest

    wire_happy_path(monkeypatch, landing_states=[ARMED])
    posts = _rerun_fakes(monkeypatch)
    original = github_actions_rest.request_with_retry

    def transport(request, **kwargs):
        response = original(request, **kwargs)
        body = response.body
        if request.method == "GET":
            if "/pulls/" in request.path and condition == "head_changed":
                body["head"]["sha"] = "2" * 40
            elif "/actions/workflows/" in request.path and condition == "superseded":
                body["workflow_runs"][0]["id"] += 1
            elif request.path.endswith("/jobs") and condition == "job_failed":
                body["jobs"][0]["conclusion"] = "failure"
            elif "workflow_id" in body:
                if condition == "active":
                    body["status"] = "in_progress"
                if condition == "repeated":
                    body["run_attempt"] = 3
        return response

    monkeypatch.setattr(github_actions_rest, "request_with_retry", transport)
    monkeypatch.setattr(
        admission,
        "read_landing",
        lambda *a, **kw: admission.LandingReadback(
            state=ARMED,
            membership=PrQueueMembership(False),
            required_checks=(CANCELLED_REQUIRED,),
        ),
    )
    monkeypatch.setattr(
        route,
        "red_entry_checks_refusal",
        lambda *a, **kw: admission.red_entry_checks_refusal(*a, **kw),
    )
    result = land(wait_for_landing=False)
    assert not result.ok
    assert reason in result.error
    assert not posts


def test_disappeared_required_check_is_not_replacement_proof(monkeypatch):
    posts = _rerun_fakes(monkeypatch)
    clock = iter([0.0, 61.0])
    refusal = recovery.redispatch_no_verdict_checks(
        None,
        "42",
        (CANCELLED_REQUIRED,),
        read_checks=lambda *a: ((), None),
        sleep=lambda *a: None,
        now=lambda: next(clock),
        lane_head="1" * 40,
    )
    assert len(posts) == 1
    assert "had not replaced" in refusal
