"""Re-running a gate re-dispatches a run that reached no verdict.

Two shapes: a correlated workflow dispatch that would rejoin a run which
concluded with no verdict, and a pull request whose required checks were
cancelled or never started. Neither may be reused; neither needs a new
commit.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain import ci_run_redispatch, merge_queue_entry_check_redispatch
from yoke_core.domain.ci_job_outcome import CI_JOB_NOT_STARTED
from yoke_core.domain.merge_queue_enqueue_verification import red_entry_checks_refusal
from yoke_core.domain.merge_queue_entry_checks import (
    entry_checks_refusal,
    only_no_verdict,
    regate_instruction,
)
from yoke_core.engines.merge_worktree_pr_check_runs import LandingCheck
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

CTX = MergeContext(args=MergeArgs(branch="ALP-1"), repo_root="", project="alpha")
RUN_URL = "https://github.com/o/r/actions/runs/37365021162/job/111944546142"
CANCELLED_REQUIRED = LandingCheck(
    name="repo-contracts",
    status="completed",
    conclusion="cancelled",
    required=True,
    url=RUN_URL,
)
FAILED_REQUIRED = LandingCheck(
    name="container",
    status="completed",
    conclusion="failure",
    required=True,
    url="https://github.com/o/r/actions/runs/37365021163/job/9",
)
QUEUED_REQUIRED = LandingCheck(
    name="repo-contracts", status="queued", required=True, url=RUN_URL
)


def _markers():
    from yoke_core.domain import deploy_pipeline_github_workflow_reconciliation as rec

    return (
        rec.WORKFLOW_DISPATCH_DISPATCHED_MARKER,
        rec.WORKFLOW_DISPATCH_RECOVERED_MARKER,
    )


def _dispatch(monkeypatch, *, triggers, polls):
    """Run ``dispatch_correlated`` against scripted trigger and poll results."""
    dispatched_marker, recovered_marker = _markers()
    keys = []

    def trigger(args, **_kwargs):
        keys.append(args[args.index("--request-id") + 1])
        run_id, fresh = triggers[len(keys) - 1]
        marker = dispatched_marker if fresh else recovered_marker
        return SimpleNamespace(returncode=0, stdout=run_id, stderr=marker)

    def github_actions(*args, **_kwargs):
        assert args[0] == "poll"
        returncode, stdout = polls[args[2]]
        return SimpleNamespace(returncode=returncode, stdout=stdout, stderr="")

    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_github_workflow_dispatch."
        "trigger_with_recovery_retries",
        trigger,
    )
    monkeypatch.setattr(
        "yoke_core.domain.deploy_pipeline_reporting._github_actions", github_actions
    )
    _result, run_id, dispatched = ci_run_redispatch.dispatch_correlated(
        project="yoke",
        repo="o/r",
        workflow="ci.yml",
        branch="YOK-1",
        request_id="qa-case:7:abc",
        timeout_seconds=60,
    )
    return run_id, dispatched, keys


def test_a_rejoined_run_with_a_verdict_is_kept(monkeypatch):
    run_id, dispatched, keys = _dispatch(
        monkeypatch, triggers=[("10", False)], polls={"10": (1, "failed:failure")}
    )

    assert (run_id, dispatched) == ("10", False)
    assert keys == ["qa-case:7:abc"]


def test_a_rejoined_in_flight_run_is_kept(monkeypatch):
    run_id, _dispatched, keys = _dispatch(
        monkeypatch, triggers=[("10", False)], polls={"10": (3, "in_progress")}
    )

    assert run_id == "10"
    assert keys == ["qa-case:7:abc"]


def test_a_rejoined_no_verdict_run_is_redispatched_through_the_chain(monkeypatch):
    run_id, dispatched, keys = _dispatch(
        monkeypatch,
        triggers=[("10", False), ("11", False), ("12", True)],
        polls={
            "10": (1, f"failed:{CI_JOB_NOT_STARTED} — no job got a runner"),
            "11": (1, "failed:cancelled"),
        },
    )

    assert (run_id, dispatched) == ("12", True)
    assert keys == [
        "qa-case:7:abc",
        "qa-case:7:abc:redispatch:10",
        "qa-case:7:abc:redispatch:11",
    ]


def test_an_endless_no_verdict_chain_refuses_by_name(monkeypatch):
    monkeypatch.setattr(ci_run_redispatch, "REPLAY_CHAIN_LIMIT", 2)
    with pytest.raises(ci_run_redispatch.RedispatchChainExhausted) as raised:
        _dispatch(
            monkeypatch,
            triggers=[("10", False), ("11", False), ("12", False)],
            polls={
                key: (1, f"failed:{CI_JOB_NOT_STARTED}") for key in ("10", "11", "12")
            },
        )

    assert "ci_redispatch_chain_exhausted" in str(raised.value)


def test_cancelled_required_checks_teach_merge_reentry_not_a_lane_fix():
    instruction = regate_instruction((CANCELLED_REQUIRED,))
    refusal = entry_checks_refusal(
        pr_num="1774",
        head_sha="d351fa576b2c",
        narrative="",
        disarm_note="merge-when-ready disarmed",
        failed=(CANCELLED_REQUIRED,),
    )

    assert only_no_verdict((CANCELLED_REQUIRED,))
    for text in (instruction, refusal):
        assert "cancelled or never started" in text
        assert "re-runs them on the same head" in text
        assert "fix it on the lane" not in text.lower()


def test_a_real_red_check_keeps_the_lane_fix_recovery():
    instruction = regate_instruction((CANCELLED_REQUIRED, FAILED_REQUIRED))

    assert not only_no_verdict((CANCELLED_REQUIRED, FAILED_REQUIRED))
    assert "fix it on the lane" in instruction


def _rerun_fakes(monkeypatch, *, post_error=None):
    posts = []

    def request(req, *, token):
        posts.append((req.method, req.path, token))
        if post_error is not None:
            raise post_error
        return SimpleNamespace(status=201, body={})

    monkeypatch.setattr(
        merge_queue_entry_check_redispatch,
        "resolve_auth_detail",
        lambda _ctx, _perms: (SimpleNamespace(repo="o/r", token="tok"), None),
    )
    monkeypatch.setattr(
        merge_queue_entry_check_redispatch, "request_with_retry", request
    )
    return posts


def test_merge_reentry_reruns_cancelled_required_checks_then_arms(monkeypatch):
    posts = _rerun_fakes(monkeypatch)
    reads = iter(
        [
            ((CANCELLED_REQUIRED,), None),
            ((CANCELLED_REQUIRED,), None),
            ((QUEUED_REQUIRED,), None),
        ]
    )

    refusal = red_entry_checks_refusal(
        CTX, "1774", read_checks=lambda _ctx, _pr: next(reads), sleep=lambda _s: None
    )

    assert refusal == ""
    assert posts == [
        ("POST", "/repos/o/r/actions/runs/37365021162/rerun-failed-jobs", "tok")
    ]


def test_merge_reentry_never_reruns_a_set_with_a_real_failure(monkeypatch):
    posts = _rerun_fakes(monkeypatch)

    refusal = red_entry_checks_refusal(
        CTX,
        "1774",
        read_checks=lambda _ctx, _pr: ((CANCELLED_REQUIRED, FAILED_REQUIRED), None),
    )

    assert "fix it on the lane" in refusal
    assert posts == []


def test_a_rerun_github_refuses_is_named_with_its_recovery(monkeypatch):
    from yoke_core.domain.gh_rest_transport import RestTransportError

    _rerun_fakes(monkeypatch, post_error=RestTransportError("403 forbidden"))

    refusal = red_entry_checks_refusal(
        CTX, "1774", read_checks=lambda _ctx, _pr: ((CANCELLED_REQUIRED,), None)
    )

    assert "re-running run 37365021162" in refusal
    assert "403 forbidden" in refusal
    assert "Re-run `yoke merge item`" in refusal


def test_checks_github_has_not_replaced_yet_refuse_with_reentry(monkeypatch):
    _rerun_fakes(monkeypatch)
    clock = iter([0.0, 0.0, 30.0, 61.0])

    refusal = merge_queue_entry_check_redispatch.redispatch_no_verdict_checks(
        CTX,
        "1774",
        (CANCELLED_REQUIRED,),
        read_checks=lambda _ctx, _pr: ((CANCELLED_REQUIRED,), None),
        sleep=lambda _s: None,
        now=lambda: next(clock),
    )

    assert "had not replaced them" in refusal
    assert "Re-run `yoke merge item`" in refusal
