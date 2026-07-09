"""REST helpers for the wrong-repo issue migration HC.

Carved out of :mod:`yoke_core.engines.doctor_hc_worktrees_gh_repo` to
keep the parent module under the authored-file cap. Provides typed
``issue_view_state`` / ``issue_view_full`` / ``issue_create`` /
``issue_comment`` / ``issue_close`` / ``issue_delete`` helpers that
issue bearer-token REST calls and return ``subprocess.CompletedProcess``
shape-compatible objects (the parent module's existing parsers expect
``returncode`` / ``stdout`` / ``stderr``).
"""

from __future__ import annotations

import json
import subprocess
from typing import List

from yoke_core.domain.gh_rest_transport import (
    RestNotFoundError,
    RestRequest,
    RestTransportError,
    request_with_retry,
)


def _ok(stdout: str = "") -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode=0, stdout=stdout, stderr="")


def _fail() -> subprocess.CompletedProcess:
    return subprocess.CompletedProcess([], returncode=1, stdout="", stderr="")


def _split(repo: str) -> tuple[str, str] | None:
    parts = repo.split("/", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        return None
    return parts[0], parts[1]


def issue_view_state(*, repo: str, num: str, token: str) -> subprocess.CompletedProcess:
    """REST equivalent of ``issue-view --jq .state``."""
    owner_name = _split(repo)
    if owner_name is None:
        return _fail()
    owner, name = owner_name
    try:
        resp = request_with_retry(
            RestRequest(method="GET", path=f"/repos/{owner}/{name}/issues/{num}"),
            token=token,
        )
    except (RestNotFoundError, RestTransportError):
        return _fail()
    body = resp.body if isinstance(resp.body, dict) else {}
    return _ok(str(body.get("state") or "").upper())


def issue_view_full(*, repo: str, num: str, token: str) -> subprocess.CompletedProcess:
    """REST equivalent of ``issue-view --json title,body,state,labels,comments``."""
    owner_name = _split(repo)
    if owner_name is None:
        return _fail()
    owner, name = owner_name
    try:
        iresp = request_with_retry(
            RestRequest(method="GET", path=f"/repos/{owner}/{name}/issues/{num}"),
            token=token,
        )
    except (RestNotFoundError, RestTransportError):
        return _fail()
    issue = iresp.body if isinstance(iresp.body, dict) else {}
    comments: List[dict] = []
    try:
        cresp = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{name}/issues/{num}/comments",
                query={"per_page": "100"},
            ),
            token=token,
        )
        body = cresp.body
        if isinstance(body, list):
            for entry in body:
                if isinstance(entry, dict):
                    comments.append({
                        "body": entry.get("body") or "",
                        "createdAt": entry.get("created_at") or "",
                        "author": {"login": (entry.get("user") or {}).get("login") or "unknown"},
                    })
    except RestTransportError:
        pass
    return _ok(json.dumps({
        "title": issue.get("title") or "",
        "body": issue.get("body") or "",
        "state": str(issue.get("state") or "").upper(),
        "labels": issue.get("labels") or [],
        "comments": comments,
    }))


def issue_create(
    *, repo: str, title: str, body: str, labels: List[str], token: str,
) -> subprocess.CompletedProcess:
    owner_name = _split(repo)
    if owner_name is None:
        return _fail()
    owner, name = owner_name
    payload: dict = {"title": title, "body": body}
    if labels:
        payload["labels"] = labels
    try:
        resp = request_with_retry(
            RestRequest(method="POST", path=f"/repos/{owner}/{name}/issues", body=payload),
            token=token,
        )
    except RestTransportError:
        return _fail()
    body_obj = resp.body if isinstance(resp.body, dict) else {}
    return _ok(str(body_obj.get("html_url") or ""))


def issue_comment(*, repo: str, num: str, body: str, token: str) -> subprocess.CompletedProcess:
    owner_name = _split(repo)
    if owner_name is None:
        return _fail()
    owner, name = owner_name
    try:
        request_with_retry(
            RestRequest(
                method="POST",
                path=f"/repos/{owner}/{name}/issues/{num}/comments",
                body={"body": body},
            ),
            token=token,
        )
    except RestTransportError:
        return _fail()
    return _ok()

def issue_close(*, repo: str, num: str, token: str) -> subprocess.CompletedProcess:
    owner_name = _split(repo)
    if owner_name is None:
        return _fail()
    owner, name = owner_name
    try:
        request_with_retry(
            RestRequest(
                method="PATCH",
                path=f"/repos/{owner}/{name}/issues/{num}",
                body={"state": "closed"},
            ),
            token=token,
        )
    except RestTransportError:
        return _fail()
    return _ok()


def issue_delete(*, repo: str, num: str, token: str) -> subprocess.CompletedProcess:
    """Best-effort GraphQL ``deleteIssue``."""
    owner_name = _split(repo)
    if owner_name is None:
        return _fail()
    owner, name = owner_name
    try:
        resp = request_with_retry(
            RestRequest(method="GET", path=f"/repos/{owner}/{name}/issues/{num}"),
            token=token,
        )
    except RestTransportError:
        return _fail()
    body = resp.body if isinstance(resp.body, dict) else {}
    node_id = str(body.get("node_id") or "")
    if not node_id:
        return _fail()
    mutation = (
        'mutation { deleteIssue(input: { issueId: "' + node_id + '" }) '
        '{ clientMutationId } }'
    )
    try:
        request_with_retry(
            RestRequest(method="POST", path="/graphql", body={"query": mutation}),
            token=token,
        )
    except RestTransportError:
        return _fail()
    return _ok()

