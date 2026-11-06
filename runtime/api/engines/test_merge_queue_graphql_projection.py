"""Private and public queue reads reject hidden evidence at their own scope."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from yoke_core.domain import merge_github_files as files
from yoke_core.domain import merge_github_membership as membership


def _wire(monkeypatch, module, payload, private):
    auth = SimpleNamespace(repo="owner/private" if private else "owner/public", token="t")

    def resolve(ctx, permissions):
        assert dict(permissions) == {"pull_requests": "read"}
        return auth, None

    def graphql(auth, *, required_permissions, **kwargs):
        assert dict(required_permissions) == {"pull_requests": "read"}
        return {"repository": {"isPrivate": private, "pullRequest": payload}}, None

    monkeypatch.setattr(module, "resolve_auth_detail", resolve)
    monkeypatch.setattr(module, "graphql_with_auth", graphql)


@pytest.mark.parametrize("private", [False, True])
def test_membership_uses_only_pull_request_read(monkeypatch, private):
    _wire(monkeypatch, membership, {
        "isInMergeQueue": False, "mergeable": "MERGEABLE", "mergeQueueEntry": None,
    }, private)
    result, error = membership.read_pr_queue_membership(object(), "42")
    assert error is None
    assert result.in_queue is False


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("field", ["isInMergeQueue", "mergeable", "mergeQueueEntry"])
def test_hidden_membership_is_not_an_absent_entry(monkeypatch, private, field):
    payload = {
        "isInMergeQueue": False, "mergeable": "MERGEABLE", "mergeQueueEntry": None,
    }
    del payload[field]
    _wire(monkeypatch, membership, payload, private)
    result, error = membership.read_pr_queue_membership(object(), "42")
    assert result is None
    assert "unreadable" in error
    assert "Pull requests: read" in error


@pytest.mark.parametrize("private", [False, True])
def test_empty_file_list_is_readable_only_with_complete_projection(monkeypatch, private):
    payload = {"files": {"nodes": [], "pageInfo": {
        "hasNextPage": False, "endCursor": None,
    }}}
    _wire(monkeypatch, files, payload, private)
    result, error = files.read_pr_changed_files(object(), "42")
    assert result == ()
    assert error is None


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("hidden", [
    "nodes", "pageInfo", "hasNextPage", "endCursor", "path", "cursor",
])
def test_hidden_file_listing_is_unreadable(monkeypatch, private, hidden):
    listing = {"nodes": [{"path": "app.py"}], "pageInfo": {
        "hasNextPage": False, "endCursor": None,
    }}
    if hidden in ("nodes", "pageInfo"):
        del listing[hidden]
    elif hidden == "path":
        listing["nodes"] = [{}]
    elif hidden == "cursor":
        listing["pageInfo"]["hasNextPage"] = True
    else:
        del listing["pageInfo"][hidden]
    original = deepcopy(listing)
    _wire(monkeypatch, files, {"files": listing}, private)
    result, error = files.read_pr_changed_files(object(), "42")
    assert result is None
    assert "unreadable" in error
    assert "Pull requests: read" in error
    assert listing == original
