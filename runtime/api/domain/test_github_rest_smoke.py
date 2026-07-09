"""Smoke + structural tests for the typed github_rest_* surface.

Covers what does NOT need a fake transport: dataclass shape, payload
parsing helpers, umbrella re-exports. The real REST-call tests live in
per-resource sibling files that mock ``request_with_retry``.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from yoke_core.domain.gh_rest_transport import (
    RestResponse,
    RestUnprocessableError,
)


def test_umbrella_reexports_resolve():
    """Every function listed in github_rest.__all__ is importable."""
    from yoke_core.domain import github_rest as gh

    for name in gh.__all__:
        assert hasattr(gh, name), f"github_rest.__all__ names {name!r} but it is not exported"


def test_dataclasses_round_trip_minimal_payloads():
    """Issue / Label / Comment parse from minimal GitHub-shaped dicts."""
    from yoke_core.domain.github_rest_comments import _parse_comment
    from yoke_core.domain.github_rest_issues import _parse_issue
    from yoke_core.domain.github_rest_labels import _parse_label

    issue = _parse_issue({
        "number": 42, "title": "Test", "state": "open", "body": "B",
        "labels": [{"name": "bug"}, {"name": "p1"}],
        "html_url": "https://github.com/o/r/issues/42",
        "user": {"login": "alice"},
    })
    assert issue.number == 42
    assert issue.title == "Test"
    assert issue.state == "OPEN"
    assert issue.labels == ("bug", "p1")
    assert issue.user_login == "alice"

    label = _parse_label({"name": "bug", "color": "ff0000", "description": "a bug"})
    assert label.name == "bug"
    assert label.color == "ff0000"
    assert label.description == "a bug"

    comment = _parse_comment({
        "id": 7, "body": "hi", "html_url": "u", "user": {"login": "bob"},
    })
    assert comment.id == 7
    assert comment.body == "hi"
    assert comment.user_login == "bob"


def test_parse_issue_handles_none_body_and_labels():
    from yoke_core.domain.github_rest_issues import _parse_issue

    issue = _parse_issue({"number": 1, "title": "T", "state": "closed",
                          "body": None, "labels": None})
    assert issue.body == ""
    assert issue.labels == ()
    assert issue.state == "CLOSED"


def test_parse_issue_rejects_non_dict():
    from yoke_core.domain.github_rest_issues import _parse_issue

    with pytest.raises(ValueError):
        _parse_issue("not a dict")


def test_target_dataclass_carries_owner_repo_split():
    from yoke_core.domain.github_rest import Target
    from yoke_core.domain.project_github_auth import ProjectGithubAuth

    auth = ProjectGithubAuth(
        project="yoke", repo="upyoke/yoke",
        token="ghs_x", env={"GH_TOKEN": "ghs_x"},
    )
    tgt = Target.from_auth(auth)
    assert tgt.owner == "upyoke"
    assert tgt.repo == "yoke"
    assert tgt.repo_slug == "upyoke/yoke"
    assert tgt.token == "ghs_x"
    assert tgt.project == "yoke"


def _api_path(path: str) -> str:
    return chr(47) + path


def test_github_rest_label_delete_encodes_label_path_segment(monkeypatch):
    from yoke_core.domain import github_rest_labels as labels

    calls = []

    def fake_request(req, *, token):
        calls.append((req.method, req.path))
        return RestResponse(status=200, headers={}, body=[])

    monkeypatch.setattr(
        labels,
        "_target_for",
        lambda project, db_path=None: SimpleNamespace(owner="o", repo="r", token="t"),
    )
    monkeypatch.setattr(labels, "request_with_retry", fake_request)

    labels.remove_labels(
        project="yoke", number=3129, labels=["status:plan drafted/next"],
    )

    assert calls[0] == (
        "DELETE",
        _api_path("repos/o/r/issues/3129/labels/status%3Aplan%20drafted%2Fnext"),
    )


def test_backlog_label_rest_encodes_label_path_segments(monkeypatch):
    from yoke_core.domain import backlog_github_label_sync_rest as rest

    calls = []

    def fake_remove_request(req, *, token):
        calls.append((req.method, req.path))
        return RestResponse(status=200, headers={}, body=[])

    monkeypatch.setattr(rest, "request_with_retry", fake_remove_request)
    rest.remove_label("o/r", 7, "status:plan drafted", token="t")
    assert calls == [
        ("DELETE", _api_path("repos/o/r/issues/7/labels/status%3Aplan%20drafted")),
    ]

    calls.clear()

    def fake_ensure_request(req, *, token):
        calls.append((req.method, req.path))
        if req.method == "POST":
            raise RestUnprocessableError("already exists")
        return RestResponse(status=200, headers={}, body={})

    monkeypatch.setattr(rest, "request_with_retry", fake_ensure_request)
    rest.ensure_label("status:plan drafted", "C5DEF5", "o/r", token="t")
    assert calls[-1] == (
        "PATCH",
        _api_path("repos/o/r/labels/status%3Aplan%20drafted"),
    )
