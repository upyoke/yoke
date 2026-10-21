"""Status-change GitHub comments use a bounded REST budget."""

from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_WRITE_PERMISSION_LEVELS,
)
from yoke_core.domain.gh_rest_transport import RestResponse, RestUnprocessableError
from yoke_core.domain.project_github_auth import ProjectGithubAuth


def test_backlog_rendering_bounds_status_comment_sync(monkeypatch):
    from yoke_core.domain import backlog_rendering

    captured: dict[str, object] = {}

    def fake_post_comment(item_id, old_status, new_status, **kwargs):
        captured["item_id"] = item_id
        captured["old_status"] = old_status
        captured["new_status"] = new_status
        captured.update(kwargs)
        return 0

    monkeypatch.setattr(
        "yoke_core.domain.backlog_github_sync.post_comment",
        fake_post_comment,
    )

    ok = backlog_rendering._post_comment(
        1902,
        "polishing-implementation",
        "implemented",
        out=StringIO(),
    )

    assert ok is True
    assert captured["item_id"] == 1902
    assert captured["github_timeout_seconds"] == (
        backlog_rendering.STATUS_COMMENT_GITHUB_TIMEOUT_SECONDS
    )
    assert captured["github_max_attempts"] == (
        backlog_rendering.STATUS_COMMENT_GITHUB_MAX_ATTEMPTS
    )


def test_status_comment_forwards_budget_to_issue_read_and_comment(monkeypatch):
    from yoke_core.domain import backlog_github_comments as comments

    calls: dict[str, object] = {}
    auth = ProjectGithubAuth(
        project="yoke",
        repo="upyoke/yoke",
        token="tok",
    )

    class FakeBacklogGithubSync:
        def _dry_run(self):
            return False

        def _github_sync_skip(self, project, operation, **kwargs):
            calls["sync_skip"] = (project, operation)
            return False

        def _issue_write_auth(self, project, public_ref, op_name, **kwargs):
            calls["auth"] = (project, public_ref, op_name)
            return auth

        def _fetch_validated_issue(self, public_ref, issue_num, **kwargs):
            calls["read"] = (public_ref, issue_num, kwargs)
            return SimpleNamespace(labels=(), state="OPEN")

    def fake_post_comment(**kwargs):
        calls["comment"] = kwargs
        return SimpleNamespace(id=1, body="ok", html_url="", user_login="")

    monkeypatch.setattr(comments, "_bgs", lambda: FakeBacklogGithubSync())
    monkeypatch.setattr(comments, "_open_conn", lambda conn: (conn, False))
    monkeypatch.setattr(comments, "_resolve_item_id", lambda item_id, conn: 1902)
    monkeypatch.setattr(comments, "_item_ref", lambda item_id, conn: "YOK-1902")
    monkeypatch.setattr(
        comments,
        "_item_context",
        lambda item_id, conn: ("#4619", "yoke", "upyoke/yoke"),
    )
    monkeypatch.setattr(comments.github_rest, "post_comment", fake_post_comment)

    rc = comments.post_comment(
        "YOK-1902",
        "polishing-implementation",
        "implemented",
        conn=object(),
        stdout=StringIO(),
        stderr=StringIO(),
        github_timeout_seconds=5.0,
        github_max_attempts=1,
    )

    assert rc == 0
    read_kwargs = calls["read"][2]  # type: ignore[index]
    assert read_kwargs["timeout_seconds"] == 5.0
    assert read_kwargs["max_attempts"] == 1
    assert read_kwargs["auth"] is auth
    assert calls["auth"] == ("yoke", "YOK-1902", "post_comment")
    assert calls["comment"]["timeout_seconds"] == 5.0  # type: ignore[index]
    assert calls["comment"]["max_attempts"] == 1  # type: ignore[index]
    assert calls["comment"]["auth"] is auth  # type: ignore[index]


def test_rest_comment_and_label_helpers_forward_budget(monkeypatch):
    from yoke_core.domain import backlog_github_label_sync_rest as labels
    from yoke_core.domain import github_rest_comments as comments

    calls: list[tuple[str, str, dict[str, object]]] = []
    target_calls: list[tuple[str, object, object]] = []

    def fake_request(req, *, token, **kwargs):
        calls.append((req.method, req.path, kwargs))
        repo_labels_path = chr(47) + "repos/o/r/labels"
        if req.method == "POST" and req.path == repo_labels_path:
            raise RestUnprocessableError("already exists")
        return RestResponse(
            status=200,
            headers={},
            body={"id": 1, "body": "ok", "html_url": "", "user": {"login": "bot"}},
        )

    def fake_target_for(project, *, required_permissions, db_path=None, auth=None):
        target_calls.append((project, db_path, required_permissions))
        return SimpleNamespace(owner="o", repo="r", token="t")

    monkeypatch.setattr(comments, "_target_for", fake_target_for)
    monkeypatch.setattr(comments, "request_with_retry", fake_request)
    comments.post_comment(
        project="yoke",
        number=1,
        body="hi",
        timeout_seconds=5.0,
        max_attempts=1,
    )

    monkeypatch.setattr(labels, "request_with_retry", fake_request)
    labels.add_labels(
        "o/r",
        1,
        ["status:implemented"],
        token="t",
        timeout_seconds=5.0,
        max_attempts=1,
    )
    labels.remove_label(
        "o/r",
        1,
        "status:polishing-implementation",
        token="t",
        timeout_seconds=5.0,
        max_attempts=1,
    )
    labels.ensure_label(
        "status:implemented",
        "C5DEF5",
        "o/r",
        token="t",
        timeout_seconds=5.0,
        max_attempts=1,
    )

    assert calls
    assert target_calls == [
        ("yoke", None, GITHUB_ISSUES_WRITE_PERMISSION_LEVELS),
    ]
    assert all(kwargs == {"timeout_seconds": 5.0, "max_attempts": 1}
               for _, _, kwargs in calls)
