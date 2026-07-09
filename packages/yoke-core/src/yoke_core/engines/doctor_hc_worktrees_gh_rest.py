"""REST helpers for the doctor GitHub-cluster HCs.

Carved out of :mod:`yoke_core.engines.doctor_hc_worktrees_gh` to keep
the parent module under the authored-file cap. Provides typed
``list_issues_by_labels_rest`` and ``search_issues_by_query_rest``
helpers consumed by ``hc_orphaned_gh_issues`` and
``hc_gh_orphan_detection``; each issues bearer-token REST calls and
returns a ``subprocess.CompletedProcess`` so the existing HC parsers
stay shape-compatible.
"""

from __future__ import annotations

import json
import subprocess
from typing import List

from yoke_core.domain.gh_rest_transport import (
    RestRequest,
    RestTransportError,
    request_with_retry,
)


def list_issues_by_labels_rest(
    *, owner: str, name: str, token: str, labels: List[str], state: str = "open",
) -> subprocess.CompletedProcess:
    """REST equivalent of ``issue-list -R o/n --label L --state X --jq .[].number``."""
    nums: List[str] = []
    for label in labels:
        per_page = 100
        page = 1
        while True:
            try:
                resp = request_with_retry(
                    RestRequest(
                        method="GET",
                        path=f"/repos/{owner}/{name}/issues",
                        query={
                            "labels": label, "state": state,
                            "per_page": str(per_page), "page": str(page),
                        },
                    ),
                    token=token,
                )
            except RestTransportError:
                return subprocess.CompletedProcess([], returncode=1, stdout="", stderr="")
            body = resp.body
            if not isinstance(body, list) or not body:
                break
            for entry in body:
                if isinstance(entry, dict) and entry.get("pull_request") is None:
                    nums.append(str(entry.get("number") or ""))
            if len(body) < per_page:
                break
            page += 1
    return subprocess.CompletedProcess(
        [], returncode=0,
        stdout="\n".join(n for n in nums if n) + ("\n" if nums else ""),
        stderr="",
    )


def search_issues_by_query_rest(
    *, owner: str, name: str, token: str, search: str, limit: int = 500,
) -> subprocess.CompletedProcess:
    """REST equivalent of ``issue-list --search S --json number,title,state``."""
    q = f"repo:{owner}/{name} {search}"
    per_page = 100
    pages = max(1, (limit + per_page - 1) // per_page)
    issues: List[dict] = []
    for page in range(1, pages + 1):
        try:
            resp = request_with_retry(
                RestRequest(
                    method="GET", path="/search/issues",
                    query={"q": q, "per_page": str(per_page), "page": str(page)},
                ),
                token=token,
            )
        except RestTransportError:
            return subprocess.CompletedProcess([], returncode=1, stdout="", stderr="")
        body = resp.body if isinstance(resp.body, dict) else {}
        items = body.get("items") if isinstance(body, dict) else None
        if not isinstance(items, list) or not items:
            break
        for entry in items:
            if isinstance(entry, dict):
                issues.append({
                    "number": entry.get("number"),
                    "title": entry.get("title") or "",
                    "state": str(entry.get("state") or "").upper(),
                })
        if len(items) < per_page:
            break
        if len(issues) >= limit:
            break
    return subprocess.CompletedProcess(
        [], returncode=0, stdout=json.dumps(issues[:limit]), stderr="",
    )
