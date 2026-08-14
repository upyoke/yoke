"""Queue-entry and membership reads: auth, refusal naming, mapping."""

from types import SimpleNamespace

from yoke_core.domain.gh_rest_transport_models import RestResponse
from yoke_core.engines import merge_worktree_pr_queue as queue_mod
from yoke_core.engines.merge_worktree_pr_rest import AuthResolutionFailed
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


def _ctx() -> MergeContext:
    return MergeContext(args=MergeArgs(branch="YOK-100"), project="yoke")


def _auth():
    return SimpleNamespace(token="tok", repo="upyoke/yoke")


def _response(body) -> RestResponse:
    return RestResponse(status=200, headers={}, body=body)


def test_enter_merge_queue_success(monkeypatch):
    monkeypatch.setattr(
        queue_mod, "resolve_auth", lambda *_a, **_kw: _auth()
    )
    calls = []

    def fake_request(req, *, token, **_kw):
        calls.append(req)
        if req.method == "GET":
            return _response({"node_id": "PR_node1"})
        return _response({"data": {"enablePullRequestAutoMerge": {
            "pullRequest": {"number": 7}}}})

    monkeypatch.setattr(queue_mod, "request_with_retry", fake_request)
    result = queue_mod.enter_merge_queue(_ctx(), "7")
    assert result.success
    assert result.pr_num == "7"
    mutation = calls[-1]
    assert mutation.path == "/graphql"
    assert mutation.body["variables"] == {"pullRequestId": "PR_node1"}


def test_enter_merge_queue_graphql_refusal_names_reason(monkeypatch):
    monkeypatch.setattr(
        queue_mod, "resolve_auth", lambda *_a, **_kw: _auth()
    )

    def fake_request(req, *, token, **_kw):
        if req.method == "GET":
            return _response({"node_id": "PR_node1"})
        return _response({"errors": [
            {"message": "Pull request Auto merge is not allowed"}]})

    monkeypatch.setattr(queue_mod, "request_with_retry", fake_request)
    result = queue_mod.enter_merge_queue(_ctx(), "7")
    assert not result.success
    assert "Auto merge is not allowed" in result.error_detail


def test_enter_merge_queue_auth_failure_carries_repair_hint(monkeypatch):
    def failing_auth(*_a, **_kw):
        raise AuthResolutionFailed("no capability", hint="yoke onboard project")

    monkeypatch.setattr(queue_mod, "resolve_auth", failing_auth)
    result = queue_mod.enter_merge_queue(_ctx(), "7")
    assert not result.success
    assert "no capability" in result.error_detail
    assert "yoke onboard project" in result.error_detail


def test_read_queue_members_maps_entries(monkeypatch):
    monkeypatch.setattr(
        queue_mod, "resolve_auth", lambda *_a, **_kw: _auth()
    )
    body = {"data": {"repository": {"mergeQueue": {"entries": {"nodes": [
        {"state": "AWAITING_CHECKS",
         "pullRequest": {"number": 11, "headRefName": "YOK-101"}},
        {"pullRequest": {"number": 12, "headRefName": "YOK-102"}},
        {"pullRequest": None},
    ]}}}}}
    monkeypatch.setattr(
        queue_mod, "request_with_retry",
        lambda req, *, token, **_kw: _response(body),
    )
    members, err = queue_mod.read_queue_members(_ctx())
    assert err is None
    assert [(m.pr_num, m.head_ref, m.state) for m in members] == [
        ("11", "YOK-101", "AWAITING_CHECKS"), ("12", "YOK-102", ""),
    ]


def test_read_queue_members_no_queue_is_named_refusal(monkeypatch):
    monkeypatch.setattr(
        queue_mod, "resolve_auth", lambda *_a, **_kw: _auth()
    )
    body = {"data": {"repository": {"mergeQueue": None}}}
    monkeypatch.setattr(
        queue_mod, "request_with_retry",
        lambda req, *, token, **_kw: _response(body),
    )
    members, err = queue_mod.read_queue_members(_ctx())
    assert members is None
    assert "no merge queue" in err
    assert "ruleset" in err


def test_read_queue_members_empty_queue_is_empty_list(monkeypatch):
    monkeypatch.setattr(
        queue_mod, "resolve_auth", lambda *_a, **_kw: _auth()
    )
    body = {"data": {"repository": {"mergeQueue": {"entries": {"nodes": []}}}}}
    monkeypatch.setattr(
        queue_mod, "request_with_retry",
        lambda req, *, token, **_kw: _response(body),
    )
    members, err = queue_mod.read_queue_members(_ctx())
    assert err is None
    assert members == []


def _wire_runs(monkeypatch, runs):
    monkeypatch.setattr(
        queue_mod, "resolve_auth_detail", lambda ctx, perms: (_auth(), None),
    )
    monkeypatch.setattr(
        queue_mod, "request_with_retry",
        lambda req, *, token, **_kw: _response({"workflow_runs": runs}),
    )


def test_read_train_run_matches_the_queue_ref_marker(monkeypatch):
    _wire_runs(monkeypatch, [
        {"head_branch": "gh-readonly-queue/main/pr-7-abc",
         "conclusion": "success", "status": "completed",
         "head_sha": "a" * 40, "html_url": "https://runs/7"},
        {"head_branch": "gh-readonly-queue/main/pr-42-def",
         "conclusion": "failure", "status": "completed",
         "head_sha": "b" * 40, "html_url": "https://runs/42"},
    ])
    run, note = queue_mod.read_train_run(_ctx(), "42")
    assert note is None
    assert run.conclusion == "failure"
    assert run.head_sha == "b" * 40
    assert run.url == "https://runs/42"


def test_read_train_run_never_substitutes_another_trains_run(monkeypatch):
    """Another train's green is not this pull request's, at any recency."""
    _wire_runs(monkeypatch, [
        {"head_branch": "gh-readonly-queue/main/pr-7-abc",
         "conclusion": "success", "status": "completed",
         "head_sha": "a" * 40, "html_url": "https://runs/7"},
    ])
    run, note = queue_mod.read_train_run(_ctx(), "42")
    assert run is None
    assert "no merge_group workflow run identified" in note
    assert "https://runs/7" not in note


def test_read_train_run_without_any_run_is_named(monkeypatch):
    _wire_runs(monkeypatch, [])
    run, note = queue_mod.read_train_run(_ctx(), "42")
    assert run is None
    assert "no merge_group workflow run" in note
