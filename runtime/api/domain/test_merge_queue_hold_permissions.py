"""Hold proves the candidate cleared through the real combined GitHub reader."""

from types import SimpleNamespace

import pytest

from yoke_core.domain import merge_queue_hold as hold
from yoke_core.domain.gh_rest_transport_models import RestResponse
from yoke_core.domain.project_github_auth_tokens import bind_local_github_user_token_provider
from yoke_core.engines import merge_worktree_pr_check_runs as checks
from yoke_core.engines import merge_worktree_pr_queue as queue
from yoke_core.engines.merge_worktree_pr_rest import GITHUB_AUTHORITY_USER
from runtime.api.engines.test_merge_worktree_pr_check_runs import _ctx, _pr_node


READ_PERMISSIONS = {
    "pull_requests": "read", "contents": "read", "checks": "read", "statuses": "read",
}


def _hold(monkeypatch, *, private, queued, failure=""):
    active = True
    requested = []
    reads = []
    mutations = []

    def resolve(_ctx, permissions):
        requested.append(dict(permissions))
        return SimpleNamespace(token="installation", repo="owner/repo"), None

    def request(req, *, token):
        assert token == "installation"
        assert "statusCheckRollup" in req.body["query"]
        reads.append(req)
        payload = _pr_node(auto_merge=active and not queued)
        pr = payload["repository"]["pullRequest"]
        pr["mergeQueueEntry"] = {"state": "QUEUED"} if active and queued else None
        body = {"data": payload}
        if (private and requested[-1] != READ_PERMISSIONS) or (
            not active and failure == "permission"
        ):
            body["errors"] = [{"message": "Resource not accessible by integration"}]
        if not active and failure == "hidden":
            del pr["mergeQueueEntry"]
        return RestResponse(status=200, headers={}, body=body)

    def mutate(_ctx, pr_number, *, required_authority):
        nonlocal active
        mutations.append(required_authority)
        active = False
        return queue.QueueEntryResult(success=True, pr_num=pr_number)

    monkeypatch.setattr(checks, "resolve_auth_detail", resolve)
    monkeypatch.setattr(queue, "request_with_retry", request)
    monkeypatch.setattr(hold, "leave_merge_queue", mutate)
    monkeypatch.setattr(hold, "dequeue_pull_request", mutate)
    with bind_local_github_user_token_provider(
        lambda: "operator", api_url="https://api.github.com",
    ):
        result = hold.hold_landing(_ctx(), pr_number="42", target="main")
    assert requested == [READ_PERMISSIONS, READ_PERMISSIONS]
    assert len(reads) == 2  # State and checks share one document per readback.
    assert mutations == [GITHUB_AUTHORITY_USER]
    return result


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("queued", [False, True])
def test_hold_reads_back_clear_with_exact_private_permissions(monkeypatch, private, queued):
    result = _hold(monkeypatch, private=private, queued=queued)
    assert result.held is True
    assert result.outcome == "held"
    assert result.after.queue_clear


@pytest.mark.parametrize("private", [False, True])
@pytest.mark.parametrize("failure", ["permission", "hidden"])
def test_hold_cannot_pass_when_confirming_projection_is_unreadable(
    monkeypatch, private, failure,
):
    result = _hold(monkeypatch, private=private, queued=True, failure=failure)
    assert result.held is False
    assert result.outcome == "unverified"
    assert not result.after.queue_readable
    expected = "Resource not accessible" if failure == "permission" else "unreadable"
    assert expected in result.refusal
    assert "repair:" in result.refusal
