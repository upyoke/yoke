"""A status transition's GitHub sync: the REST calls it makes and the end state.

``sync_labels`` and ``post_comment`` run after every status change. Each
resolves its write authorization once and reads the issue once; the status
label moves once (in ``sync_labels``), and the comment touches no label.
The fake records every REST request at the transport boundary and applies
the label writes to an in-memory issue, so the test pins both the call
sequence and the labels and comment GitHub ends up with.
"""

from __future__ import annotations

import io
from unittest.mock import patch

from runtime.api.backlog_github_sync_test_helpers import make_db
from runtime.api.conftest import insert_item
from yoke_core.domain import backlog_github_sync, backlog_github_transport
from yoke_core.domain.gh_rest_transport import RestResponse, RestUnprocessableError
from yoke_core.domain.project_github_auth import ProjectGithubAuth

_ISSUE = "/repos/org/externalwebapp/issues/55"
_REST_MODULES = (
    "yoke_core.domain.backlog_github_label_sync_rest",
    "yoke_core.domain.github_rest_issues",
    "yoke_core.domain.github_rest_comments",
)


class _FakeGithub:
    def __init__(self, labels: list[str]) -> None:
        self.labels = list(labels)
        self.comments: list[str] = []
        self.calls: list[tuple[str, str]] = []

    def request(self, req, *, token, **_kwargs):
        self.calls.append((req.method, req.path))
        if req.method == "GET":
            return self._issue()
        if req.method == "POST" and req.path == "/repos/org/externalwebapp/labels":
            raise RestUnprocessableError("already exists")
        if req.method == "POST" and req.path == f"{_ISSUE}/labels":
            self.labels += [x for x in req.body["labels"] if x not in self.labels]
        elif req.method == "DELETE":
            self.labels.remove(req.path.rsplit("/", 1)[1].replace("%3A", ":"))
        elif req.method == "POST" and req.path == f"{_ISSUE}/comments":
            self.comments.append(req.body["body"])
            return RestResponse(200, {}, {"id": 1, "body": req.body["body"]})
        return RestResponse(200, {}, {})

    def _issue(self) -> RestResponse:
        body = {
            "number": 55,
            "title": "t",
            "state": "open",
            "labels": [{"name": label} for label in self.labels],
        }
        return RestResponse(200, {}, body)


def test_status_transition_makes_seven_calls_and_lands_the_same_labels():
    conn = make_db()
    insert_item(
        conn, id=91, workflow_id="issue", status="implementing", priority="high",
        project="externalwebapp", github_issue="#55",
    )
    conn.execute(
        "UPDATE projects SET github_sync_mode = 'enabled' WHERE slug = 'externalwebapp'"
    )
    conn.commit()
    github = _FakeGithub(["status:idea", "priority:high", "workflow:issue"])
    auth = ProjectGithubAuth(
        project="externalwebapp", repo="org/externalwebapp", token="t"
    )
    patches = [
        patch(f"{module}.request_with_retry", side_effect=github.request)
        for module in _REST_MODULES
    ]
    try:
        with patch.object(
            backlog_github_transport, "resolve_project_github_auth", return_value=auth,
        ) as resolve, patches[0], patches[1], patches[2]:
            labels_rc = backlog_github_sync.sync_labels(
                91, conn=conn, stdout=io.StringIO(), stderr=io.StringIO()
            )
            comment_rc = backlog_github_sync.post_comment(
                91, "idea", "implementing", conn=conn,
                stdout=io.StringIO(), stderr=io.StringIO(),
            )
    finally:
        conn.close()

    assert (labels_rc, comment_rc) == (0, 0)
    assert resolve.call_count == 2  # once per sync, not once per call
    assert github.calls == [
        ("GET", _ISSUE),
        ("DELETE", f"{_ISSUE}/labels/status%3Aidea"),
        ("POST", "/repos/org/externalwebapp/labels"),
        ("PATCH", "/repos/org/externalwebapp/labels/status%3Aimplementing"),
        ("POST", f"{_ISSUE}/labels"),
        ("GET", _ISSUE),
        ("POST", f"{_ISSUE}/comments"),
    ]
    assert sorted(github.labels) == [
        "priority:high", "status:implementing", "workflow:issue",
    ]
    assert github.comments == ["**Status:** `idea` → `implementing`"]
