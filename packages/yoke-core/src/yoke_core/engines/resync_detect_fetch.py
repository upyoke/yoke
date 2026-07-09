"""GitHub fetch helpers for resync detection (bearer-token REST).

The :func:`_fetch_gh_issues_per_project` helper returns a per-project mapping.
On normal fetch the per-project value is ``{issue_number: issue}``; on
:class:`ProjectGithubAuthError` from the canonical resolver the value becomes
the sentinel dict ``{"_auth_error": "<code>", "_repair_hint": "<text>"}``.

The sentinel exists so the engine continues processing healthy projects after
one project's auth fails -- Yoke is the control plane and re-raises at the
top boundary; per-project failures for non-Yoke projects surface as
detection-result warnings. Downstream consumers that iterate the per-project
value MUST check for the ``_auth_error`` key before treating it as an issues
map.

GitHub I/O dispatches through
:mod:`yoke_core.domain.gh_rest_transport` (GitHub App auth). Tests patch the REST
transport surface directly.
"""

from __future__ import annotations

from typing import Dict, List

from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestRequest,
    RestTransportError,
    request_with_retry,
)
from yoke_core.domain.project_github_auth import (
    InvalidToken,
    ProjectGithubAuthError,
    repair_command_hint,
    resolve_project_github_auth,
)


def _auth_failure_sentinel(error: ProjectGithubAuthError) -> Dict[str, str]:
    """Render the typed auth failure as the per-project sentinel dict."""
    return {
        "_auth_error": error.code,
        "_repair_hint": repair_command_hint(error, error.project),
    }


# Per-project sentinel key marking a project whose GitHub sync mode is
# backlog_only. Mirrors the ``_auth_error`` sentinel shape: downstream
# consumers skip classification for the project entirely — its items are
# never orphans, never drift, never repaired.
SYNC_DISABLED_KEY = "_sync_disabled"


def _sync_disabled_sentinel(mode: str) -> Dict[str, str]:
    """Render a disabled sync mode as the per-project sentinel dict."""
    return {SYNC_DISABLED_KEY: mode}


def _project_sync_disabled(per_project_value: Dict) -> bool:
    """True when ``per_project_value`` carries the sync-disabled sentinel."""
    return (
        isinstance(per_project_value, dict)
        and SYNC_DISABLED_KEY in per_project_value
    )


def _list_issues_via_rest(
    repo: str,
    *,
    token: str,
    state: str = "all",
    limit: int = 9999,
) -> List[Dict]:
    """Paginate ``/repos/{owner}/{repo}/issues`` returning legacy-shaped dicts."""
    parts = repo.split("/", 1)
    if len(parts) != 2:
        return []
    owner, name = parts

    per_page = 100
    pages = max(1, (limit + per_page - 1) // per_page)
    collected: List[Dict] = []
    for page in range(1, pages + 1):
        resp = request_with_retry(
            RestRequest(
                method="GET",
                path=f"/repos/{owner}/{name}/issues",
                query={
                    "state": state,
                    "per_page": str(per_page),
                    "page": str(page),
                },
            ),
            token=token,
        )
        body = resp.body
        if not isinstance(body, list):
            break
        if not body:
            break
        for entry in body:
            if not isinstance(entry, dict):
                continue
            if entry.get("pull_request") is not None:
                continue
            collected.append({
                "number": entry.get("number"),
                "title": entry.get("title") or "",
                "labels": [
                    {"name": lab.get("name", "")}
                    for lab in (entry.get("labels") or [])
                    if isinstance(lab, dict)
                ],
                "state": str(entry.get("state") or "").upper(),
                "body": entry.get("body") or "",
            })
        if len(body) < per_page:
            break
        if len(collected) >= limit:
            break
    return collected[:limit]


def _fetch_gh_issues_per_project(project_map: Dict[str, str]) -> Dict[str, Dict]:
    """Fetch GitHub issues per project; record per-project auth failures.

    Yoke (the control plane) re-raises ``ProjectGithubAuthError`` so the
    engine boundary can fail-closed before any classification work happens.
    Non-Yoke auth failures land in the result dict as the ``_auth_error``
    sentinel and the loop continues with the remaining projects.
    """
    by_project: Dict[str, Dict] = {}

    # Yoke fetch -- fail-closed at the engine boundary, so let
    # ProjectGithubAuthError propagate. Skipped entirely when the caller
    # excluded yoke from the map (its GitHub sync mode is backlog_only).
    if "yoke" in project_map:
        yoke_auth = resolve_project_github_auth("yoke")
        try:
            yoke_issues = _list_issues_via_rest(
                yoke_auth.repo, token=yoke_auth.token,
            )
        except RestAuthError as exc:
            raise InvalidToken(
                "yoke", f"REST rejected token for project 'yoke': {exc}"
            ) from exc
        by_project["yoke"] = {i["number"]: i for i in yoke_issues}

    # Non-yoke projects -- per-project catch keeps the loop alive.
    for proj, repo in project_map.items():
        if proj == "yoke" or not repo:
            continue
        try:
            auth = resolve_project_github_auth(proj)
        except ProjectGithubAuthError as exc:
            by_project[proj] = _auth_failure_sentinel(exc)
            continue
        try:
            issues = _list_issues_via_rest(auth.repo, token=auth.token)
        except RestAuthError as exc:
            by_project[proj] = _auth_failure_sentinel(
                InvalidToken(proj, f"REST rejected token for project '{proj}': {exc}")
            )
            continue
        except RestTransportError:
            by_project[proj] = {}
            continue
        by_project[proj] = {i["number"]: i for i in issues}

    return by_project


def _graphql_batch_fetch(
    nums: List[int],
    owner: str,
    repo: str,
    project: str = "yoke",
    batch_size: int = 50,
) -> Dict[int, Dict]:
    """Fetch issue bodies and comments via batched GraphQL (bearer-token REST).

    GitHub exposes GraphQL at ``/graphql``; the canonical GitHub App auth transport
    handles auth + retry. Returns ``{issue_number: {number, body, comments}}``
    shaped as a stable dict so callers stay independent of REST response detail.
    """
    result_map: Dict[int, Dict] = {}
    if not nums or not owner or not repo:
        return result_map

    try:
        auth = resolve_project_github_auth(project)
    except ProjectGithubAuthError:
        return result_map

    for i in range(0, len(nums), batch_size):
        batch = nums[i:i + batch_size]
        fields = []
        for num in batch:
            fields.append(
                f"    issue_{num}: issue(number: {num}) {{\n"
                f"      number\n"
                f"      body\n"
                f"      comments(first: 100) {{\n"
                f"        nodes {{\n"
                f"          body\n"
                f"        }}\n"
                f"      }}\n"
                f"    }}"
            )

        query = (
            "{\n"
            f'  repository(owner: "{owner}", name: "{repo}") {{\n'
            + "\n".join(fields) + "\n"
            + "  }\n"
            + "}"
        )

        try:
            resp = request_with_retry(
                RestRequest(
                    method="POST",
                    path="/graphql",
                    body={"query": query},
                ),
                token=auth.token,
            )
        except RestTransportError:
            continue

        payload = resp.body if isinstance(resp.body, dict) else {}
        repo_data = payload.get("data", {}).get("repository", {}) if isinstance(payload, dict) else {}
        if not isinstance(repo_data, dict):
            continue
        for key, value in repo_data.items():
            if value is None or not isinstance(value, dict):
                continue
            comments_nodes = (value.get("comments") or {}).get("nodes") or []
            result_map[value["number"]] = {
                "number": value["number"],
                "body": value.get("body", "") or "",
                "comments": comments_nodes,
            }

    return result_map
