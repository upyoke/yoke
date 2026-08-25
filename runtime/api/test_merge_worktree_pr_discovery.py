"""Finding a branch's pull request, and reading GitHub's create refusals."""

from types import SimpleNamespace

from yoke_core.domain.gh_rest_transport import RestUnprocessableError
from yoke_core.domain.gh_rest_transport_models import RestResponse
from yoke_core.engines import merge_worktree_pr_discovery as discovery_mod
from yoke_core.engines import merge_worktree_pr_rest as rest_mod
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext

LANE_SHA = "1" * 40
MERGED_SHA = "2" * 40


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
    # GitHub allows one open pull request per head and base, so this asks
    # for no ordering — and canned-response fixtures key on the exact
    # query, so widening it silently misses them.
    assert received[0].query == {"head": "upyoke:YOK-200", "state": "open"}


def test_landable_lookup_sees_a_merged_one(monkeypatch):
    received = _wire_listing(monkeypatch, [
        {"number": 183, "html_url": "https://gh/183", "state": "closed"},
    ])
    url, num, refusal = discovery_mod.find_landable_pull_request(_ctx())
    assert (url, num, refusal) == ("https://gh/183", "183", "")
    assert received[0].query["state"] == "all"
    assert received[0].query["sort"] == "updated"
    assert received[0].query["direction"] == "desc"


def test_landable_lookup_prefers_the_open_one(monkeypatch):
    _wire_listing(monkeypatch, [
        {"number": 183, "html_url": "https://gh/183", "state": "closed"},
        {"number": 190, "html_url": "https://gh/190", "state": "open"},
    ])
    _, num, refusal = discovery_mod.find_landable_pull_request(_ctx())
    assert (num, refusal) == ("190", "")


def test_landable_lookup_without_any_is_empty(monkeypatch):
    _wire_listing(monkeypatch, [])
    assert discovery_mod.find_landable_pull_request(_ctx()) == (None, None, "")


def test_merged_pull_request_covering_the_lane_head_is_landable(monkeypatch):
    """The lane committed nothing since; this merge is the landing."""
    _wire_listing(monkeypatch, [{
        "number": 183, "html_url": "https://gh/183", "state": "closed",
        "merged_at": "2026-01-01T00:00:00Z", "head": {"sha": LANE_SHA},
    }])
    _, num, refusal = discovery_mod.find_landable_pull_request(
        _ctx(), lane_head=LANE_SHA,
    )
    assert (num, refusal) == ("183", "")


def test_merged_pull_request_behind_the_lane_head_is_declined(monkeypatch):
    """One commit past the merged head means this lane has not landed.

    Converging here would bind the new head to the old merge commit and
    record evidence for work that never reached the base branch.
    """
    _wire_listing(monkeypatch, [{
        "number": 183, "html_url": "https://gh/183", "state": "closed",
        "merged_at": "2026-01-01T00:00:00Z", "head": {"sha": MERGED_SHA},
    }])
    url, num, refusal = discovery_mod.find_landable_pull_request(
        _ctx(), lane_head=LANE_SHA,
    )
    assert (url, num) == (None, None)
    assert "183" in refusal
    assert MERGED_SHA[:12] in refusal
    assert LANE_SHA[:12] in refusal


def test_a_lane_the_base_already_contains_is_not_declined(monkeypatch):
    """A lane fast-forwarded onto the base after its merge has landed.

    Its head differs from the merged head — it *is* the merge commit — and
    calling that "commits beyond the pull request that merged it" sent
    close-out off to open a second pull request for work already on main.
    """
    _wire_listing(monkeypatch, [{
        "number": 183, "html_url": "https://gh/183", "state": "closed",
        "merged_at": "2026-01-01T00:00:00Z", "head": {"sha": MERGED_SHA},
    }])
    monkeypatch.setattr(discovery_mod.git, "is_landed", lambda *_a: True)
    ctx = MergeContext(
        args=MergeArgs(branch="YOK-200", target="main"),
        project="yoke",
        repo_root="/repo",
    )

    _, num, refusal = discovery_mod.find_landable_pull_request(
        ctx, lane_head=LANE_SHA,
    )

    assert (num, refusal) == ("183", "")


def test_a_lane_the_base_lacks_is_still_declined_with_a_checkout(monkeypatch):
    _wire_listing(monkeypatch, [{
        "number": 183, "html_url": "https://gh/183", "state": "closed",
        "merged_at": "2026-01-01T00:00:00Z", "head": {"sha": MERGED_SHA},
    }])
    monkeypatch.setattr(discovery_mod.git, "is_landed", lambda *_a: False)
    ctx = MergeContext(
        args=MergeArgs(branch="YOK-200", target="main"),
        project="yoke",
        repo_root="/repo",
    )

    url, num, refusal = discovery_mod.find_landable_pull_request(
        ctx, lane_head=LANE_SHA,
    )

    assert (url, num) == (None, None)
    assert LANE_SHA[:12] in refusal


def test_closed_unmerged_pull_request_is_still_returned(monkeypatch):
    """Only a merged pull request claims to have landed the lane."""
    _wire_listing(monkeypatch, [{
        "number": 183, "html_url": "https://gh/183", "state": "closed",
        "head": {"sha": MERGED_SHA},
    }])
    _, num, refusal = discovery_mod.find_landable_pull_request(
        _ctx(), lane_head=LANE_SHA,
    )
    assert (num, refusal) == ("183", "")


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
