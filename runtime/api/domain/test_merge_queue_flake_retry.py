"""One durable flake reservation per pull request and input pair."""

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.merge_queue_observer_test_helpers import observer_connection
from runtime.api.merge_queue_landing_test_helpers import LANE_SHA, ctx
from yoke_core.domain import merge_queue_failed_train as failed
from yoke_core.domain.handlers import merge_queue_flake_retry as handler
from yoke_core.domain.merge_queue_flake_retry import RETRY_SECTION, claim_retry
from yoke_core.domain.item_json_sections import section_write_refusal
from yoke_core.engines.merge_worktree_pr_train_run import TrainRun

BASE = "3" * 40
RUN_URL = "https://github.com/example/project/actions/runs/123"


def body(**changes):
    return handler.ClaimRetryRequest.model_validate({
        "pr_number": "42", "head_sha": LANE_SHA, "base_sha": BASE,
        "run_url": RUN_URL, "reason": "test_clock: scheduler timing unrelated to diff",
        **changes,
    })


def test_budget_survives_commits_and_new_runs_but_new_inputs_get_a_budget():
    conn = observer_connection()
    assert handler.reserve_retry(conn, 101, body(), "worker")
    conn.commit()
    assert not handler.reserve_retry(conn, 101, body(run_url=RUN_URL + "4"), "successor")
    assert handler.reserve_retry(conn, 101, body(base_sha="5" * 40), "worker")
    assert handler.reserve_retry(conn, 101, body(head_sha="6" * 40), "worker")
    stored = json.loads(conn.execute(
        "SELECT content FROM item_sections WHERE item_id=? AND section_name=?",
        (101, RETRY_SECTION),
    ).fetchone()[0])
    assert len(stored["retries"]) == 3
    assert stored["retries"][0]["run_url"] == RUN_URL
    assert stored["retries"][0]["reason"].startswith("test_clock:")
    assert section_write_refusal(RETRY_SECTION)


def test_corrupt_history_never_resets_the_budget():
    conn = observer_connection()
    handler.reserve_retry(conn, 101, body(), "worker")
    conn.execute("UPDATE item_sections SET content='broken' WHERE section_name=?", (RETRY_SECTION,))
    with pytest.raises(ValueError):
        handler.reserve_retry(conn, 101, body(), "worker")


def test_failed_train_retry_dispatches_the_exact_failed_inputs_once():
    conn = observer_connection()
    calls = []

    def dispatch(**kwargs):
        calls.append(kwargs)
        allowed = handler.reserve_retry(conn, 101, body(**kwargs["payload"]), "worker")
        return SimpleNamespace(
            success=allowed, result={"claimed": allowed},
            error=SimpleNamespace(code="merge_train_flake_retry_exhausted", message="Fix the cause"),
        )

    def enter():
        return failed.unchanged_failed_train_refusal(
            ctx(), "42", lane_head=LANE_SHA, base_branch="main", base_sha=BASE,
            parents=[BASE, LANE_SHA],
            train=TrainRun(conclusion="failure", head_sha="4" * 40, url=RUN_URL),
            retry_flake=body().reason, public_ref=f"ITEM-{42}", dispatch=dispatch,
        )

    assert enter() is None
    assert "merge_train_flake_retry_exhausted" in enter()
    assert calls[0]["payload"]["run_url"] == RUN_URL
    assert calls[0]["payload"]["base_sha"] == BASE


def test_missing_or_failed_reservation_never_authorizes_arming():
    for response in [
        SimpleNamespace(success=True, result={}),
        SimpleNamespace(success=False, error=SimpleNamespace(code="function_version_skew", message="required serving floor")),
    ]:
        error = claim_retry(f"ITEM-{42}", "42", LANE_SHA, BASE, RUN_URL, "test_clock", dispatch=lambda **kw: response)
        assert "no re-enqueue was sent" in error


def test_named_second_retry_refusal_teaches_item_ownership(monkeypatch):
    from yoke_contracts.api.function_call import ActorContext, FunctionCallRequest, TargetRef

    conn = observer_connection()
    class Connection:
        def __enter__(self):
            return conn
        def __exit__(self, *args):
            return False
    monkeypatch.setattr(handler.db_helpers, "connect", lambda: Connection())
    request = FunctionCallRequest(
        function="merge_queue.flake_retry.claim", actor=ActorContext(session_id="worker"),
        target=TargetRef(kind="item", item_id=101), payload=body().model_dump(),
    )
    assert handler.handle_claim_retry(request).primary_success
    refused = handler.handle_claim_retry(request)
    assert refused.error.code == "merge_train_flake_retry_exhausted"
    assert "second failure belongs to this item" in refused.error.message


def test_automatic_reentry_mints_contents_write_and_pull_requests_write(monkeypatch):
    from yoke_core.domain.project_github_auth_tokens import scoped_installation_token_permissions
    from yoke_core.engines import merge_worktree_pr_queue as queue_mod

    scopes = []
    def resolve(_ctx, *, required_permissions, **kwargs):
        scopes.append(scoped_installation_token_permissions(required_permissions))
        return SimpleNamespace(token="tok", repo="example/project")
    monkeypatch.setattr(queue_mod, "resolve_auth", resolve)
    monkeypatch.setattr(queue_mod, "_pr_node_id", lambda *_: ("node", None))
    monkeypatch.setattr(queue_mod, "graphql_with_auth", lambda *_a, **_kw: ({}, None))
    assert queue_mod.enter_merge_queue(ctx(), "7", expected_head_sha="a" * 40).success
    assert scopes == [{"metadata": "read", "contents": "write", "pull_requests": "write"}]


def test_serving_observer_compares_failed_inputs_without_a_checkout(monkeypatch):
    from dataclasses import replace

    scopes, requests = [], []
    def auth(_ctx, permissions):
        scopes.append(dict(permissions))
        return SimpleNamespace(repo="example/project", token="token"), None
    def read(request, **kwargs):
        requests.append(request.path)
        if "/git/commits/" in request.path:
            return SimpleNamespace(body={"parents": [{"sha": BASE}, {"sha": LANE_SHA}]})
        return SimpleNamespace(body={"sha": BASE})
    monkeypatch.setattr(failed, "resolve_auth_detail", auth)
    monkeypatch.setattr(failed, "request_with_retry", read)
    error = failed.unchanged_failed_train_refusal(
        replace(ctx(), repo_root=""), "42", lane_head=LANE_SHA,
        base_branch="feature/base", train=TrainRun(
            conclusion="failure", head_sha="4" * 40, url=RUN_URL,
        ),
    )
    assert "failed-train-unchanged" in error
    assert requests[-1] == "/repos/example/project/commits/feature%2Fbase"
    assert all(scope == {"contents": "read"} for scope in scopes)


def test_serving_observer_ancestry_uses_github_compare(monkeypatch):
    from dataclasses import replace

    monkeypatch.setattr(failed, "_github_commit_read", lambda *_: {"status": "ahead"})
    assert failed._base_covers_train(replace(ctx(), repo_root=""), BASE, "4" * 40)
    monkeypatch.setattr(failed, "_github_commit_read", lambda *_: {})
    assert not failed._base_covers_train(replace(ctx(), repo_root=""), BASE, "4" * 40)
