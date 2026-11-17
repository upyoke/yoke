"""Draft landing promotion, refusal safety, and read-only readiness."""

from dataclasses import replace
from types import SimpleNamespace

import pytest

from yoke_core.domain import merge_github_queue as github
from yoke_core.domain import merge_pr_readiness as ready
from yoke_core.domain import merge_queue_admission_gates as gates
from yoke_core.domain import merge_queue_route as route
from yoke_core.domain.merge_landing_readiness import LandingReadiness
from yoke_core.domain.merge_github_queue import QueueEntryResult
from runtime.api.merge_queue_landing_test_helpers import (
    UNARMED, ARMED, MERGED, land, wire_happy_path,
)
from runtime.api.merge_worktree_pr_checks_test_support import (
    _arm_pr_merge_environment, _stub_ctx,
)

DRAFT = replace(UNARMED, draft=True, merge_state_status="unknown")


@pytest.mark.parametrize("draft", [True, False])
def test_rest_read_uses_draft_even_while_mergeability_is_unknown(monkeypatch, draft):
    monkeypatch.setattr(github, "resolve_auth_detail", lambda *a, **k: (
        SimpleNamespace(repo="owner/repo", token="test"), None,
    ))
    monkeypatch.setattr(github, "request_with_retry", lambda *a, **k: SimpleNamespace(
        body={"draft": draft, "mergeable_state": "unknown", "state": "open"},
    ))
    state, error = github.read_pr_landing_state(_stub_ctx(), "42")
    assert error is None
    assert state.draft is draft


@pytest.mark.parametrize("error", [None, "github graphql refused: permission denied"])
def test_ready_mutation_and_named_refusal(monkeypatch, error):
    monkeypatch.setattr(github, "resolve_auth_detail", lambda *a, **k: (
        SimpleNamespace(repo="owner/repo", token="test"), None,
    ))
    monkeypatch.setattr(github, "_pr_node_id", lambda *a: ("PR_node", "unknown", None))
    calls = []

    def graphql(auth, *, query, variables, required_permissions):
        calls.append((query, variables))
        return None, error

    monkeypatch.setattr(github, "graphql_with_auth", graphql)
    result = github.mark_ready_for_review(_stub_ctx(), "42")
    assert len(calls) == 1
    assert "markPullRequestReadyForReview" in calls[0][0]
    assert calls[0][1] == {"pullRequestId": "PR_node"}
    assert result.success is (error is None)
    if error:
        assert result.error_detail.startswith("pr_ready_for_review_failed:")
        assert error in result.error_detail
        assert "mark PR 42 ready on GitHub and re-run `yoke merge item`" in result.error_detail


@pytest.mark.parametrize("draft,refuse", [(True, False), (True, True), (False, False)])
def test_queue_prepares_before_arming_and_stops_on_refusal(monkeypatch, draft, refuse):
    wire_happy_path(monkeypatch, landing_states=[DRAFT if draft else UNARMED, ARMED, MERGED])
    calls = []
    original_enter = route.enter_merge_queue

    def promote(*a):
        calls.append("ready")
        return QueueEntryResult(success=not refuse, error_detail="pr_ready_for_review_failed: denied")

    def enter(*a, **k):
        calls.append("arm")
        return original_enter(*a, **k)

    monkeypatch.setattr(route, "mark_ready_for_review", promote)
    monkeypatch.setattr(route, "enter_merge_queue", enter)
    emitted = []
    outcome = land(emit=emitted.append)
    assert calls == (["ready"] if refuse else ["ready", "arm"] if draft else ["arm"])
    assert outcome.ok is (not refuse)
    if refuse:
        assert "pr_ready_for_review_failed" in outcome.error
    elif draft:
        assert "marked PR 42 ready for review" in emitted


@pytest.mark.parametrize("draft,refuse", [(True, False), (True, True), (False, False)])
def test_standalone_prepares_before_merge_and_stops_on_refusal(monkeypatch, draft, refuse):
    from yoke_core.engines import merge_worktree_pr as engine
    from yoke_core.domain.merge_github_rest import PrMergeResult

    _arm_pr_merge_environment(
        monkeypatch, ci_outcome=SimpleNamespace(outcome="passed"), test_results="",
    )
    monkeypatch.setattr(engine, "prepare_pull_request", ready.prepare_pull_request)
    monkeypatch.setattr(ready, "read_pr_landing_state", lambda *a: (DRAFT if draft else UNARMED, None))
    calls = []

    def promote(*a):
        calls.append("ready")
        return QueueEntryResult(success=not refuse, error_detail="pr_ready_for_review_failed: denied")

    def merge(*a):
        calls.append("merge")
        return PrMergeResult(success=True)

    monkeypatch.setattr(ready, "mark_ready_for_review", promote)
    monkeypatch.setattr(engine, "run_pr_merge_with_retry_guard", merge)
    result = engine.do_pr_merge(_stub_ctx())
    assert calls == (["ready"] if refuse else ["ready", "merge"] if draft else ["merge"])
    assert result == (1 if refuse else 0)


def test_standalone_unreadable_pr_refuses_before_mutation(monkeypatch):
    monkeypatch.setattr(ready, "read_pr_landing_state", lambda *a: (None, "read denied"))
    monkeypatch.setattr(ready, "mark_ready_for_review", lambda *a: pytest.fail("must not mutate"))
    error = ready.prepare_pull_request(_stub_ctx(), "42", emit=lambda s: None)
    assert "pr_ready_for_review_failed: read denied" in error


@pytest.mark.parametrize("draft", [True, False])
@pytest.mark.parametrize("queue", [True, False])
def test_check_reports_promotion_without_mutation(monkeypatch, draft, queue):
    readiness = LandingReadiness(public_ref=f"APP-{1}", branch="lane", repo_root="/tmp/repo", target="main")
    state = DRAFT if draft else UNARMED
    for module in (github, ready, route):
        monkeypatch.setattr(module, "mark_ready_for_review", lambda *a: pytest.fail("check must not mutate"))
    if queue:
        monkeypatch.setattr(gates, "queue_admission_refusals", lambda *a, **k: gates.QueueGate())
        monkeypatch.setattr(gates, "list_branch_pull_requests", lambda *a, **k: SimpleNamespace(
            error=None, rows=[{"number": 42, "state": "open"}],
        ))
        monkeypatch.setattr(gates, "read_pr_landing_state", lambda *a: (state, None))
        monkeypatch.setattr(gates, "read_train_run", lambda *a: (None, None))
        gates.check_queue_gates(readiness, item={}, head="a" * 40)
    else:
        monkeypatch.setattr(ready, "find_existing_pr", lambda *a: ("https://example/pull/42", "42"))
        monkeypatch.setattr(ready, "read_pr_landing_state", lambda *a: (state, None))
        ready.check_standalone_draft(readiness, item={})
    assert readiness.ready
    assert readiness.merge_will == (["mark PR 42 ready for review"] if draft else [])
