"""Queue-order reads need only PR authority and must never hide entries."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from yoke_core.domain.gh_rest_transport_models import RestResponse
from yoke_core.engines import merge_worktree_pr_queue as queue
from runtime.api.engines.merge_worktree_pr_check_runs_test_support import _ctx


def _payload():
    return {"repository": {"mergeQueue": {"entries": {
        "pageInfo": {"hasNextPage": False},
        "nodes": [{
            "state": "QUEUED", "pullRequest": {"number": 42, "headRefName": "feature"},
        }],
    }}}}


def _read(monkeypatch, payload, private):
    permissions = []

    def resolve(_ctx, required_permissions):
        permissions.append(dict(required_permissions))
        return SimpleNamespace(token="installation", repo="owner/repo"), None

    def request(req, *, token):
        assert token == "installation"
        assert "mergeQueue(branch:" in req.body["query"]
        body = {"data": payload}
        if private and permissions[-1] != {"pull_requests": "read"}:
            body = {"errors": [{"message": "Resource not accessible by integration"}]}
        return RestResponse(status=200, headers={}, body=body)

    monkeypatch.setattr(queue, "resolve_auth_detail", resolve)
    result = queue.read_queue_members(_ctx(), request=request)
    assert permissions == [{"pull_requests": "read"}]
    return result


@pytest.mark.parametrize("private", [False, True])
def test_complete_queue_read_requests_exact_authority(monkeypatch, private):
    members, error = _read(monkeypatch, _payload(), private)
    assert error is None
    assert members == [queue.QueueMember("42", "feature", "QUEUED")]


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("path", [
    ("repository",), ("repository", "mergeQueue"),
    ("repository", "mergeQueue", "entries"),
    ("repository", "mergeQueue", "entries", "pageInfo"),
    ("repository", "mergeQueue", "entries", "pageInfo", "hasNextPage"),
    ("repository", "mergeQueue", "entries", "nodes"),
    ("repository", "mergeQueue", "entries", "nodes", 0, "state"),
    ("repository", "mergeQueue", "entries", "nodes", 0, "pullRequest"),
    ("repository", "mergeQueue", "entries", "nodes", 0, "pullRequest", "number"),
    ("repository", "mergeQueue", "entries", "nodes", 0, "pullRequest", "headRefName"),
])
@pytest.mark.parametrize("hidden", ["missing", "null"])
def test_hidden_queue_order_never_becomes_empty(monkeypatch, private, path, hidden):
    payload = deepcopy(_payload())
    parent = payload
    for key in path[:-1]:
        parent = parent[key]
    if hidden == "missing":
        del parent[path[-1]]
    else:
        parent[path[-1]] = None
    members, error = _read(monkeypatch, payload, private)
    assert members is None
    assert error
    assert "unreadable" in error or "no merge queue" in error


@pytest.mark.parametrize("private", [False, True])
def test_paginated_queue_order_is_incomplete(monkeypatch, private):
    payload = _payload()
    payload["repository"]["mergeQueue"]["entries"]["pageInfo"]["hasNextPage"] = True
    members, error = _read(monkeypatch, payload, private)
    assert members is None
    assert "queue_order_incomplete" in error
