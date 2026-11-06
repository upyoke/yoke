"""Landing reads request every private field's authority and fail closed."""

from copy import deepcopy

import pytest

from yoke_core.engines import merge_worktree_pr_check_runs as checks
from runtime.api.engines.merge_worktree_pr_check_runs_test_support import (
    _auth,
    _check_run,
    _ctx,
    _pr_node,
    _wire,
)


@pytest.mark.parametrize("private", [False, True])
def test_landing_query_requests_its_exact_permissions(monkeypatch, private):
    expected = {
        "pull_requests": "read", "contents": "read",
        "checks": "read", "statuses": "read",
    }
    calls = []

    def resolve(_ctx, permissions):
        calls.append(dict(permissions))
        return _auth(), None

    def graphql(_auth, *, query, variables, required_permissions):
        assert dict(required_permissions) == expected
        # Public data can mask missing authority; private data cannot.
        if private and calls[-1] != expected:
            return None, "Resource not accessible by integration"
        return _pr_node(), None

    monkeypatch.setattr(checks, "resolve_auth_detail", resolve)
    monkeypatch.setattr(checks, "graphql_with_auth", graphql)
    result = checks.read_pr_landing_and_required_checks(_ctx(), "42")
    assert calls == [expected]
    assert result.state is not None
    assert result.required_checks == ()
    assert result.checks_error is None


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("field", [
    "merged", "closed", "state", "autoMergeRequest", "mergeQueueEntry",
    "mergeStateStatus", "headRefOid", "mergedAt", "mergeCommit", "commits",
])
def test_hidden_landing_field_is_unreadable(monkeypatch, private, field):
    payload = _pr_node()
    payload["repository"]["isPrivate"] = private
    del payload["repository"]["pullRequest"][field]
    _wire(monkeypatch, payload)
    result = checks.read_pr_landing_and_required_checks(_ctx(), "42")
    assert result.state is None
    assert result.required_checks is None
    assert field in result.checks_error
    assert "repair:" in result.checks_error


@pytest.mark.parametrize("field", [
    "__typename", "isRequired", "name", "status", "conclusion", "startedAt",
])
def test_hidden_check_field_cannot_become_no_required_checks(monkeypatch, field):
    node = _check_run(name="ci", status="COMPLETED", conclusion="SUCCESS")
    del node[field]
    _wire(monkeypatch, _pr_node(contexts=[node]))
    result = checks.read_pr_landing_and_required_checks(_ctx(), "42")
    assert result.required_checks is None
    assert "unreadable" in result.checks_error


@pytest.mark.parametrize("field", ["context", "state", "isRequired", "createdAt"])
def test_hidden_commit_status_cannot_pass(monkeypatch, field):
    node = {
        "__typename": "StatusContext", "context": "legacy-ci", "state": "SUCCESS",
        "isRequired": True, "createdAt": "2026-09-21T00:00:00Z", "targetUrl": "",
    }
    del node[field]
    _wire(monkeypatch, _pr_node(contexts=[node]))
    result = checks.read_pr_landing_and_required_checks(_ctx(), "42")
    assert result.required_checks is None
    assert field in result.checks_error


@pytest.mark.parametrize("commits", [
    None, {}, {"nodes": None}, {"nodes": []}, {"nodes": [None]},
    {"nodes": [{"commit": {}}]},
    {"nodes": [{"commit": {"statusCheckRollup": {}}}]},
])
def test_hidden_commit_rollup_cannot_pass(monkeypatch, commits):
    payload = _pr_node()
    payload["repository"]["pullRequest"]["commits"] = deepcopy(commits)
    _wire(monkeypatch, payload)
    result = checks.read_pr_landing_and_required_checks(_ctx(), "42")
    assert result.state is None
    assert result.required_checks is None
    assert "unreadable" in result.checks_error


@pytest.mark.parametrize("private", [False, True])
def test_partial_graphql_permission_error_cannot_pass(monkeypatch, private):
    payload = _pr_node(merged=True)
    payload["repository"]["isPrivate"] = private
    _wire(monkeypatch, payload, "Resource not accessible by integration")
    result = checks.read_pr_landing_and_required_checks(_ctx(), "42")
    assert result.state is None
    assert result.required_checks is None
    assert "Resource not accessible" in result.checks_error
    assert "Commit statuses read" in result.checks_error
