"""Issue search does not lose private issues or silently accept hidden results."""

from types import SimpleNamespace

import pytest

from yoke_core.domain import github_rest, github_rest_issues as issues
from yoke_core.domain.gh_rest_transport import RestAuthError, RestTransportError
from yoke_core.domain.gh_rest_transport_models import RestResponse


def _wire(monkeypatch, *, private, payload):
    requested = []

    def resolve(project, *, required_permissions, db_path=None):
        requested.append(dict(required_permissions))
        return SimpleNamespace(owner="owner", repo="repo", token="scoped")

    def request(req, *, token):
        assert req.path == "/search/issues"
        assert token == "scoped"
        body = payload
        if private and requested[-1] == {"metadata": "read"}:
            body = {"total_count": 0, "incomplete_results": False, "items": []}
        return RestResponse(status=200, headers={}, body=body)

    monkeypatch.setattr(github_rest, "resolve_target", resolve)
    monkeypatch.setattr(issues, "request_with_retry", request)
    return requested


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("search,permissions", [
    ("word is:issue", {"issues": "read"}),
    ("word type:issue", {"issues": "read"}),
    ("word is:pr", {"pull_requests": "read"}),
    ("word type:pr", {"pull_requests": "read"}),
    ("word", {"issues": "read", "pull_requests": "read"}),
    ('"word is:issue inside literal"', {"issues": "read", "pull_requests": "read"}),
    ("is:issue is:pr", {"issues": "read", "pull_requests": "read"}),
])
def test_search_grants_match_its_issue_or_pr_filter(monkeypatch, private, search, permissions):
    payload = {"total_count": 1, "incomplete_results": False, "items": [{
        "number": 42, "title": "Visible result", "state": "open",
    }]}
    requested = _wire(monkeypatch, private=private, payload=payload)
    result = issues.list_issues(project="project", search=search)
    assert requested == [permissions]
    assert [item.number for item in result] == [42]


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("payload", [
    None, {}, {"items": []},
    {"total_count": 0, "incomplete_results": False},
    {"total_count": 0, "incomplete_results": False, "items": None},
    {"total_count": 0, "incomplete_results": True, "items": []},
    {"total_count": 1, "incomplete_results": False, "items": [None]},
    {"total_count": 1, "incomplete_results": False, "items": [{}]},
])
def test_hidden_or_incomplete_search_cannot_become_no_issues(monkeypatch, private, payload):
    _wire(monkeypatch, private=private, payload=payload)
    with pytest.raises(RestTransportError, match="issue_search_unreadable.*repair:"):
        issues.list_issues(project="project", search="is:issue")


@pytest.mark.parametrize("private", [False, True])
def test_complete_zero_result_search_is_readable(monkeypatch, private):
    _wire(monkeypatch, private=private, payload={
        "total_count": 0, "incomplete_results": False, "items": [],
    })
    assert issues.list_issues(project="project", search="is:issue") == []


@pytest.mark.parametrize("private", [False, True])
def test_search_permission_error_is_not_empty_results(monkeypatch, private):
    _wire(monkeypatch, private=private, payload=None)

    def request(*_args, **_kwargs):
        raise RestAuthError("Resource not accessible by integration", status=403)

    monkeypatch.setattr(issues, "request_with_retry", request)
    with pytest.raises(RestAuthError, match="Resource not accessible"):
        issues.list_issues(project="project", search="is:issue")
