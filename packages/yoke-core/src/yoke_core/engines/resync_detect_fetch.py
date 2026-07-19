"""GitHub fetch helpers for resync detection (bearer-token REST).

The :func:`_fetch_gh_issues_per_project` helper returns a per-project mapping.
On normal fetch the per-project value is ``{issue_number: issue}``; when a
non-control-plane project's GitHub state cannot be read, the value is an
explicit unavailable sentinel.  Downstream stages must skip classification
and repair for unavailable projects instead of treating a failed read as an
empty repository.

GitHub I/O dispatches through
:mod:`yoke_core.domain.gh_rest_transport` (GitHub App auth). Tests patch the REST
transport surface directly.
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import Dict, Iterable, List

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_ISSUES_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.gh_rest_transport import (
    RestAuthError,
    RestRequest,
    RestTransportError,
    request_with_retry,
)
from yoke_core.domain.project_github_auth import (
    InvalidToken,
    MissingRepoMetadata,
    ProjectGithubAuth,
    ProjectGithubAuthError,
    TransportFailure,
    repair_command_hint,
    resolve_project_github_auth,
)


UNAVAILABLE_KEY = "_github_unavailable"
UNAVAILABLE_CODE_KEY = "_unavailable_code"
UNAVAILABLE_HINT_KEY = "_repair_hint"
UNAVAILABLE_STAGE_KEY = "_unavailable_stage"
GRAPHQL_BATCH_WORKERS = 4


def _unavailable_sentinel(
    error: ProjectGithubAuthError,
    *,
    stage: str,
) -> Dict[str, str]:
    """Render a typed GitHub read failure as a per-project sentinel."""
    return {
        UNAVAILABLE_KEY: "true",
        UNAVAILABLE_CODE_KEY: error.code,
        UNAVAILABLE_HINT_KEY: repair_command_hint(error, error.project),
        UNAVAILABLE_STAGE_KEY: stage,
    }


def _auth_failure_sentinel(
    error: ProjectGithubAuthError,
    *,
    stage: str = "issues",
) -> Dict[str, str]:
    """Render an auth failure as the shared unavailable state."""
    return _unavailable_sentinel(error, stage=stage)


def _transport_failure_sentinel(
    project: str,
    error: RestTransportError,
    *,
    stage: str,
) -> Dict[str, str]:
    """Render a REST/GraphQL transport failure without leaking response data."""
    typed = TransportFailure(
        project,
        f"GitHub {stage} read failed for project '{project}': {error}",
    )
    return _unavailable_sentinel(typed, stage=stage)


def _project_unavailable(per_project_value: Dict) -> bool:
    """True when GitHub state was not completely available for a project."""
    return (
        isinstance(per_project_value, dict)
        and UNAVAILABLE_KEY in per_project_value
    )


# Per-project sentinel key marking a project whose GitHub sync mode is
# backlog_only. Mirrors the unavailable sentinel shape: downstream
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
    if len(parts) != 2 or not all(parts):
        raise RestTransportError("resolved GitHub repository metadata is invalid")
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
            raise RestTransportError("GitHub issues endpoint returned an invalid payload")
        if not body:
            break
        for entry in body:
            if not isinstance(entry, dict):
                raise RestTransportError(
                    "GitHub issues endpoint returned an invalid issue entry"
                )
            if entry.get("pull_request") is not None:
                continue
            number = entry.get("number")
            if not isinstance(number, int) or number <= 0:
                raise RestTransportError(
                    "GitHub issues endpoint returned an issue without a valid number"
                )
            collected.append({
                "number": number,
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


def _fetch_gh_issues_per_project(projects: Iterable[str]) -> Dict[str, Dict]:
    """Fetch GitHub issues per project; record per-project read failures.

    Yoke (the control plane) re-raises ``ProjectGithubAuthError`` so the
    engine boundary can fail-closed before any classification work happens.
    Non-Yoke failures land in the result dict as the unavailable sentinel and
    the loop continues with the remaining projects. Repository and token
    always come from the same canonical auth resolution.
    """
    by_project: Dict[str, Dict] = {}
    project_slugs = tuple(sorted(set(projects)))

    # Yoke fetch -- fail-closed at the engine boundary, so let
    # ProjectGithubAuthError propagate. Skipped entirely when the caller
    # excluded yoke from the map (its GitHub sync mode is backlog_only).
    if "yoke" in project_slugs:
        yoke_auth = resolve_project_github_auth(
            "yoke", required_permissions=GITHUB_ISSUES_READ_PERMISSION_LEVELS,
        )
        try:
            yoke_issues = _list_issues_via_rest(
                yoke_auth.repo, token=yoke_auth.token,
            )
        except RestAuthError as exc:
            raise InvalidToken(
                "yoke", f"REST rejected token for project 'yoke': {exc}"
            ) from exc
        except RestTransportError as exc:
            raise TransportFailure(
                "yoke", f"GitHub issues read failed for project 'yoke': {exc}"
            ) from exc
        by_project["yoke"] = {i["number"]: i for i in yoke_issues}

    # Non-yoke projects -- per-project catch keeps the loop alive.
    for proj in project_slugs:
        if proj == "yoke":
            continue
        try:
            auth = resolve_project_github_auth(
                proj,
                required_permissions=GITHUB_ISSUES_READ_PERMISSION_LEVELS,
            )
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
        except RestTransportError as exc:
            by_project[proj] = _transport_failure_sentinel(
                proj, exc, stage="issues",
            )
            continue
        by_project[proj] = {i["number"]: i for i in issues}

    return by_project


def _graphql_batch_fetch(
    nums: List[int],
    project: str = "yoke",
    batch_size: int = 50,
    *,
    auth: ProjectGithubAuth | None = None,
) -> Dict[int, Dict]:
    """Fetch issue bodies and comments via batched GraphQL (bearer-token REST).

    GitHub exposes GraphQL at ``/graphql``; the canonical GitHub App auth transport
    handles auth + retry. Returns ``{issue_number: {number, body, comments}}``
    shaped as a stable dict so callers stay independent of REST response detail.
    """
    result_map: Dict[int, Dict] = {}
    if not nums:
        return result_map

    resolved = auth or resolve_project_github_auth(
        project,
        required_permissions=GITHUB_ISSUES_READ_PERMISSION_LEVELS,
    )
    parts = resolved.repo.split("/", 1)
    if len(parts) != 2 or not all(parts):
        raise MissingRepoMetadata(
            project,
            f"project '{project}' has invalid bound GitHub repository metadata",
        )
    owner, repo = parts

    batches = [nums[i:i + batch_size] for i in range(0, len(nums), batch_size)]

    def fetch_batch(batch: List[int]) -> Dict[int, Dict]:
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

        resp = request_with_retry(
            RestRequest(
                method="POST",
                path="/graphql",
                body={"query": query},
                replay_safe=True,
            ),
            token=resolved.token,
        )

        payload = resp.body
        if not isinstance(payload, dict):
            raise RestTransportError(
                f"GitHub GraphQL returned an invalid payload for project '{project}'"
            )
        if payload.get("errors"):
            raise RestTransportError(
                f"GitHub GraphQL returned errors for project '{project}'"
            )
        data = payload.get("data")
        repo_data = data.get("repository") if isinstance(data, dict) else None
        if not isinstance(repo_data, dict):
            raise RestTransportError(
                f"GitHub GraphQL omitted repository data for project '{project}'"
            )
        expected_keys = {f"issue_{number}" for number in batch}
        if not expected_keys.issubset(repo_data):
            raise RestTransportError(
                f"GitHub GraphQL returned incomplete issue data for project '{project}'"
            )
        batch_result: Dict[int, Dict] = {}
        for key, value in repo_data.items():
            if value is None or not isinstance(value, dict):
                continue
            number = value.get("number")
            comments = value.get("comments")
            if (
                not isinstance(number, int)
                or number <= 0
                or not isinstance(comments, dict)
                or not isinstance(comments.get("nodes"), list)
            ):
                raise RestTransportError(
                    f"GitHub GraphQL returned invalid issue data for project '{project}'"
                )
            comments_nodes = comments["nodes"]
            batch_result[number] = {
                "number": number,
                "body": value.get("body", "") or "",
                "comments": comments_nodes,
            }
        return batch_result

    worker_count = min(GRAPHQL_BATCH_WORKERS, len(batches))
    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        for batch_result in executor.map(fetch_batch, batches):
            result_map.update(batch_result)

    return result_map
