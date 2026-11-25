"""Hosted proof dispatch against the registered handler and a real intent store."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

import pytest

from runtime.api.fixtures.file_test_db import init_test_db
from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef
from yoke_contracts.github_workflow_dispatch import (
    WORKFLOW_DISPATCH_CORRELATION_INPUT,
    workflow_dispatch_marker,
)
from yoke_core.domain import (
    github_actions_rest,
    github_workflow_dispatch as dispatch,
    github_workflow_dispatch_intents as intents,
    platform_consumer_dispatch_recovery as recovery,
)
from yoke_core.domain.ci_run_redispatch import redispatch_request_id
from yoke_core.domain.gh_rest_transport import RestNetworkError
from yoke_core.domain.handlers import github_actions_workflow_dispatch as handler
from yoke_core.domain.platform_consumer_dispatch import (
    CONSUMER_CHECK_WORKFLOW,
    CONSUMER_REPO,
    PENDING_JOIN_BUDGET_SECONDS,
    consumer_dispatch_tag,
    pair_request_id,
)

CANDIDATE = "a" * 40
CONSUMER = "b" * 40
TAG = consumer_dispatch_tag(CONSUMER)
BASE_KEY = pair_request_id(CANDIDATE, CONSUMER)
RUNS = f"/repos/{CONSUMER_REPO}/actions/workflows/{CONSUMER_CHECK_WORKFLOW}/runs"
TAG_API = f"/repos/{CONSUMER_REPO}/git/ref/tags/{TAG}"


def _run(marker, *, run_id=71, status="queued", conclusion=None):
    return {
        "id": run_id,
        "display_title": f"platform-release-pin-check {CANDIDATE} on {CONSUMER} {workflow_dispatch_marker(marker)}",
        "head_sha": CONSUMER,
        "event": "workflow_dispatch",
        "path": f".github/workflows/{CONSUMER_CHECK_WORKFLOW}",
        "status": status,
        "conclusion": conclusion,
    }


@dataclass
class Provider:
    key: str
    now: datetime = datetime(2026, 11, 25, 16, tzinfo=timezone.utc)
    runs: list[dict] = field(default_factory=list)
    posted: list[dict] = field(default_factory=list)
    tag_commit: str = CONSUMER
    lost_posts: int = 1
    total_count: int | None = None
    lookup_failure: bool = False
    tag_reads: int = 0
    posted_replacement: threading.Event = field(default_factory=threading.Event)
    wait_for_replacement: bool = False

    def get(self, path, *, token, query=None):
        if path == RUNS:
            assert query["event"] == "workflow_dispatch"
            assert "created" in query
            if self.lookup_failure:
                raise RestNetworkError("GitHub did not return a run listing")
            if self.wait_for_replacement and intents.latest_intent(self.key).attempt > 1:
                assert self.posted_replacement.wait(5)
            count = len(self.runs) if self.total_count is None else self.total_count
            size = int(query["per_page"])
            start = (int(query["page"]) - 1) * size
            return {"total_count": count, "workflow_runs": self.runs[start:start + size]}
        if path == TAG_API:
            self.tag_reads += 1
            return {"ref": f"refs/tags/{TAG}", "object": {"type": "commit", "sha": self.tag_commit}}
        return next(run for run in self.runs if path == f"/repos/{CONSUMER_REPO}/actions/runs/{run['id']}")

    def post(self, path, *, body, token, max_attempts):
        assert path == RUNS.removesuffix("/runs") + "/dispatches"
        self.posted.append(body)
        if len(self.posted) <= self.lost_posts:
            raise RestNetworkError("dispatch response lost")
        run_id = 71 + len(self.posted)
        self.runs.append(_run(body["inputs"][WORKFLOW_DISPATCH_CORRELATION_INPUT], run_id=run_id))
        self.posted_replacement.set()
        return {"workflow_run_id": run_id}

    def invoke(self, actor="release-driver"):
        request = FunctionCallRequest(
            function="github_actions.workflow.dispatch",
            actor=ActorContext(actor_id=actor, session_id=f"session-{actor}"),
            target=TargetRef(kind="global"),
            request_id=self.key,
            payload={
                "repo": CONSUMER_REPO,
                "workflow": CONSUMER_CHECK_WORKFLOW,
                "ref": TAG,
                "inputs": {"product_ref": CANDIDATE, "consumer_sha": CONSUMER},
                "project": "platform",
                "correlation_input": WORKFLOW_DISPATCH_CORRELATION_INPUT,
            },
            options={"authorized_project_id": 3},
        )
        return handler.handle_workflow_dispatch(request)

    def advance_window(self):
        self.now += timedelta(seconds=PENDING_JOIN_BUDGET_SECONDS)


@pytest.fixture(params=[BASE_KEY, redispatch_request_id(BASE_KEY, "42")], ids=["pair", "wheel-recovery"])
def provider(request, tmp_path, monkeypatch):
    fake = Provider(request.param)
    monkeypatch.setattr(
        handler, "_validate_and_resolve",
        lambda call, model, *a, **kw: (model(**call.payload), "platform-app", None),
    )
    monkeypatch.setattr(recovery, "rest_get", fake.get)
    monkeypatch.setattr(github_actions_rest, "rest_get", fake.get)
    monkeypatch.setattr(github_actions_rest, "rest_post", fake.post)
    monkeypatch.setattr(intents, "utc_now", lambda: fake.now)
    monkeypatch.setattr(recovery, "utc_now", lambda: fake.now)
    with init_test_db(tmp_path):
        yield fake


@pytest.mark.parametrize(
    "status,conclusion", [("queued", None), ("completed", "failure")],
)
def test_bridge_joins_a_late_exact_run_without_replacing_its_verdict(provider, status, conclusion):
    assert provider.invoke().error.code == "workflow_dispatch_ambiguous"
    provider.now += timedelta(seconds=PENDING_JOIN_BUDGET_SECONDS - 1)
    assert provider.invoke().error.code == "workflow_dispatch_pending"
    provider.now += timedelta(seconds=1)
    original = intents.latest_intent(provider.key)
    provider.runs.append(_run(original.correlation_id, status=status, conclusion=conclusion))

    for actor in ("bridge-ci", "release-driver"):
        joined = provider.invoke(actor)
        assert joined.result_payload["run_id"] == "71"
        assert not joined.result_payload["dispatched"]
    assert len(provider.posted) == 1
    assert provider.tag_reads == 0


def test_earlier_pending_attempt_can_appear_after_a_replacement_loses_its_response(provider):
    provider.lost_posts = 2
    assert provider.invoke().error.code == "workflow_dispatch_ambiguous"
    first = intents.latest_intent(provider.key)
    provider.advance_window()
    assert provider.invoke().error.code == "workflow_dispatch_ambiguous"
    second = intents.latest_intent(provider.key)
    assert second.attempt == 2
    provider.runs.append(_run(first.correlation_id, status="completed", conclusion="success"))

    for actor in ("bridge-ci", "release-driver"):
        assert provider.invoke(actor).result_payload["run_id"] == "71"
    assert len(provider.posted) == 2
    assert intents.intent_by_correlation(first.correlation_id).workflow_run_id == "71"
    assert intents.intent_by_correlation(second.correlation_id).state == "pending"


def test_stage_and_production_share_the_next_attempt_and_the_bridge_can_join(provider, monkeypatch):
    assert provider.invoke().error.code == "workflow_dispatch_ambiguous"
    first = intents.latest_intent(provider.key)
    provider.advance_window()
    assert provider.invoke("bridge-ci").error.code == "workflow_dispatch_pending"
    assert len(provider.posted) == 1
    assert provider.tag_reads == 0

    barrier = threading.Barrier(2)
    claim = dispatch.claim_attempt

    def concurrent_claim(**kwargs):
        assert kwargs["attempt"] == 2
        barrier.wait(timeout=5)
        return claim(**kwargs)

    monkeypatch.setattr(dispatch, "claim_attempt", concurrent_claim)
    provider.wait_for_replacement = True
    with ThreadPoolExecutor(max_workers=2) as callers:
        stage = callers.submit(provider.invoke)
        production = callers.submit(provider.invoke)
        marked = [stage.result(timeout=10).result_payload, production.result(timeout=10).result_payload]
    assert sorted((item["run_id"], item["dispatched"]) for item in marked) == [
        ("73", False), ("73", True),
    ]
    assert provider.invoke("bridge-ci").result_payload["run_id"] == "73"
    assert len(provider.posted) == 2
    for body in provider.posted:
        assert body["ref"] == TAG
        assert body["inputs"]["product_ref"] == CANDIDATE
        assert body["inputs"]["consumer_sha"] == CONSUMER
    assert intents.intent_by_correlation(first.correlation_id).state == "pending"
    assert intents.latest_intent(provider.key).attempt == 2


@pytest.mark.parametrize(
    "case,code",
    [
        ("transport", "consumer_proof_lookup_unavailable"),
        ("incomplete", "consumer_proof_lookup_incomplete"),
        ("moved-tag", "consumer_proof_tag_unverified"),
        ("head_sha", "consumer_proof_identity_mismatch"),
        ("event", "consumer_proof_identity_mismatch"),
        ("path", "consumer_proof_identity_mismatch"),
        ("display_title", "consumer_proof_identity_mismatch"),
    ],
)
def test_uncertain_or_wrong_evidence_cannot_authorize_replacement(provider, case, code):
    assert provider.invoke().error.code == "workflow_dispatch_ambiguous"
    first = intents.latest_intent(provider.key)
    provider.advance_window()
    if case == "transport":
        provider.lookup_failure = True
    elif case == "incomplete":
        provider.total_count = 1
    elif case == "moved-tag":
        provider.tag_commit = "d" * 40
    else:
        run = _run(first.correlation_id)
        run[case] = (
            run[case].replace(CANDIDATE, "d" * 40) if case == "display_title" else "different"
        )
        provider.runs.append(run)
    outcome = provider.invoke()
    assert outcome.error.code == code
    assert outcome.error.recovery_hint
    assert len(provider.posted) == 1
    assert intents.latest_intent(provider.key) == first


def test_completion_during_tag_verification_prevents_stale_replacement(provider, monkeypatch):
    assert provider.invoke().error.code == "workflow_dispatch_ambiguous"
    first = intents.latest_intent(provider.key)
    provider.advance_window()

    def verify_after_other_caller_recovers(payload, token):
        provider.runs.append(_run(first.correlation_id))
        intents.complete_intent(first, workflow_run_id="71", run_url=None, html_url=None)

    monkeypatch.setattr(dispatch, "verify_consumer_tag", verify_after_other_caller_recovers)
    assert provider.invoke().result_payload["run_id"] == "71"
    assert len(provider.posted) == 1


def test_bridge_joins_original_run_after_replacement_is_rejected(provider, monkeypatch):
    from yoke_core.domain.gh_rest_transport import RestUnprocessableError

    assert provider.invoke().error.code == "workflow_dispatch_ambiguous"
    first = intents.latest_intent(provider.key)
    provider.advance_window()

    def reject(*args, **kwargs):
        raise RestUnprocessableError("dispatch was rejected", status=422)

    monkeypatch.setattr(github_actions_rest, "rest_post", reject)
    assert provider.invoke().error.code == "workflow_dispatch_rejected"
    assert intents.latest_intent(provider.key).state == "rejected"
    provider.runs.append(_run(first.correlation_id))
    assert provider.invoke("bridge-ci").result_payload["run_id"] == "71"
    provider.lookup_failure = True
    assert provider.invoke().result_payload["run_id"] == "71"
    assert intents.latest_intent(provider.key).state == "rejected"


def test_pagination_joins_a_match_after_the_first_page(provider, monkeypatch):
    assert provider.invoke().error.code == "workflow_dispatch_ambiguous"
    intent = intents.latest_intent(provider.key)
    provider.advance_window()
    monkeypatch.setattr(recovery, "CORRELATION_RUNS_PER_PAGE", 2)
    provider.runs.extend([
        _run("different-one", run_id=91),
        _run("different-two", run_id=92),
        _run(intent.correlation_id),
    ])

    assert provider.invoke().result_payload["run_id"] == "71"
    assert len(provider.posted) == 1


def test_pagination_budget_is_not_evidence_of_absence(provider, monkeypatch):
    assert provider.invoke().error.code == "workflow_dispatch_ambiguous"
    provider.advance_window()
    monkeypatch.setattr(recovery, "CORRELATION_SEARCH_PAGES", 1)
    monkeypatch.setattr(recovery, "CORRELATION_RUNS_PER_PAGE", 2)
    provider.runs.extend([
        _run("different-one", run_id=91),
        _run("different-two", run_id=92),
        _run("different-three", run_id=93),
    ])

    assert provider.invoke().error.code == "consumer_proof_lookup_incomplete"
    assert provider.tag_reads == 0
    assert len(provider.posted) == 1
