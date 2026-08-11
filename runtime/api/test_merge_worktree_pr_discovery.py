"""Finding a branch's pull request, and reading GitHub's create refusals."""

from types import SimpleNamespace

from yoke_core.domain.gh_rest_transport import RestUnprocessableError
from yoke_core.domain.gh_rest_transport_models import RestResponse
from yoke_core.engines import merge_worktree_pr_discovery as discovery_mod
from yoke_core.engines import merge_worktree_pr_rest as rest_mod
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


def _ctx() -> MergeContext:
    return MergeContext(
        args=MergeArgs(branch="YOK-200", target="main"), project="yoke",
    )


def _auth():
    return SimpleNamespace(token="tok", repo="upyoke/yoke")


def _wire_listing(monkeypatch, rows):
    """Serve one pull-request listing; return the requests it received."""
    monkeypatch.setattr(
        discovery_mod, "resolve_auth", lambda *_a, **_kw: _auth()
    )
    received: list = []

    def fake_request(req, *, token, **_kw):
        received.append(req)
        return RestResponse(status=200, headers={}, body=rows)

    monkeypatch.setattr(discovery_mod, "request_with_retry", fake_request)
    return received


def test_find_existing_pr_asks_only_for_open_pull_requests(monkeypatch):
    received = _wire_listing(monkeypatch, [
        {"number": 42, "html_url": "https://gh/42", "state": "open"},
    ])
    url, num = discovery_mod.find_existing_pr(_ctx())
    assert (url, num) == ("https://gh/42", "42")
    assert received[0].query["state"] == "open"
    assert received[0].query["head"] == "upyoke:YOK-200"


def test_find_branch_pull_request_sees_a_merged_one(monkeypatch):
    received = _wire_listing(monkeypatch, [
        {"number": 183, "html_url": "https://gh/183", "state": "closed"},
    ])
    url, num = discovery_mod.find_branch_pull_request(_ctx())
    assert (url, num) == ("https://gh/183", "183")
    assert received[0].query["state"] == "all"


def test_find_branch_pull_request_prefers_the_open_one(monkeypatch):
    _wire_listing(monkeypatch, [
        {"number": 183, "html_url": "https://gh/183", "state": "closed"},
        {"number": 190, "html_url": "https://gh/190", "state": "open"},
    ])
    _, num = discovery_mod.find_branch_pull_request(_ctx())
    assert num == "190"


def test_find_branch_pull_request_without_any_is_empty(monkeypatch):
    _wire_listing(monkeypatch, [])
    assert discovery_mod.find_branch_pull_request(_ctx()) == (None, None)


def _wire_create_refusal(monkeypatch, message):
    monkeypatch.setattr(rest_mod, "resolve_auth", lambda *_a, **_kw: _auth())

    def fake_request(req, *, token, **_kw):
        raise RestUnprocessableError(message, status=422, body=message)

    monkeypatch.setattr(rest_mod, "request_with_retry", fake_request)
    return rest_mod.create_pr(_ctx(), title="t", body="b")


def test_create_pr_reads_a_no_commits_refusal_as_an_absent_diff(monkeypatch):
    result = _wire_create_refusal(
        monkeypatch, "No commits between main and YOK-200",
    )
    assert result.no_commits
    assert not result.already_exists
    assert result.error_detail is None


def test_create_pr_still_reads_an_existing_pull_request(monkeypatch):
    result = _wire_create_refusal(
        monkeypatch, "A pull request already exists for upyoke:YOK-200",
    )
    assert result.already_exists
    assert not result.no_commits


def test_create_pr_keeps_other_refusals_hard(monkeypatch):
    result = _wire_create_refusal(monkeypatch, "base branch is protected")
    assert not result.no_commits
    assert not result.already_exists
    assert "HTTP 422" in result.error_detail
