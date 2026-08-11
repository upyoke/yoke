"""The landing's file set, read from the pull request GitHub merged."""

from types import SimpleNamespace

from yoke_core.domain.gh_rest_transport_models import RestResponse
from yoke_core.engines import merge_worktree_pr_files as files_mod
from yoke_core.engines import merge_worktree_pr_queue as queue_mod
from yoke_core.engines.merge_worktree_prepare import MergeArgs, MergeContext


def _ctx() -> MergeContext:
    return MergeContext(args=MergeArgs(branch="YOK-100"), project="yoke")


def _auth():
    return SimpleNamespace(token="tok", repo="upyoke/yoke")


def _response(body) -> RestResponse:
    return RestResponse(status=200, headers={}, body=body)


def _wire(monkeypatch, pages):
    monkeypatch.setattr(
        files_mod, "resolve_auth_detail", lambda ctx, perms: (_auth(), None),
    )
    seen: list = []

    def fake_request(req, *, token, **_kw):
        seen.append(req.body["variables"])
        return _response(pages[min(len(seen) - 1, len(pages) - 1)])

    monkeypatch.setattr(queue_mod, "request_with_retry", fake_request)
    return seen


def _page(paths, *, has_next=False, cursor="") -> dict:
    return {"data": {"repository": {"pullRequest": {"files": {
        "pageInfo": {"hasNextPage": has_next, "endCursor": cursor},
        "nodes": [{"path": path} for path in paths],
    }}}}}


def test_pages_until_the_listing_ends(monkeypatch):
    """A branch wider than one page must not report a truncated file set."""
    seen = _wire(monkeypatch, [
        _page(["a.py", "b.py"], has_next=True, cursor="cursor1"),
        _page(["b.py", "c.py"]),
    ])

    paths, err = files_mod.read_pr_changed_files(_ctx(), "42")

    assert err is None
    assert paths == ("a.py", "b.py", "c.py")
    assert seen[0] == {
        "owner": "upyoke", "name": "yoke", "number": 42, "cursor": None,
    }
    assert seen[1]["cursor"] == "cursor1"


def test_refusal_is_named(monkeypatch):
    _wire(monkeypatch, [{"errors": [{"message": "Resource not accessible"}]}])

    paths, err = files_mod.read_pr_changed_files(_ctx(), "42")

    assert paths is None
    assert "Resource not accessible" in err


def test_missing_listing_is_named(monkeypatch):
    """An absent listing is unresolved, never an empty change set."""
    _wire(monkeypatch, [{"data": {"repository": {"pullRequest": None}}}])

    paths, err = files_mod.read_pr_changed_files(_ctx(), "42")

    assert paths is None
    assert "no file listing" in err


def test_auth_failure_is_surfaced(monkeypatch):
    monkeypatch.setattr(
        files_mod, "resolve_auth_detail",
        lambda ctx, perms: (None, "no capability (repair: yoke onboard project)"),
    )

    paths, err = files_mod.read_pr_changed_files(_ctx(), "42")

    assert paths is None
    assert "yoke onboard project" in err
