"""Answer a project's commit comparison over its own repository provider.

A control plane serving an HTTPS-only project holds no checkout of that
project, so the comparison runs over the binding the project already
authorized. One compare read returns the exact commit set between two
lineages together with each commit's parents, message, and time, which is
every fact the local checkout was consulted for — the first-parent range is
then walked out of that graph rather than approximated.
"""

from __future__ import annotations

from typing import Any, Mapping, Sequence

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.deployment_run_carried_work_source import (
    RELATION_AHEAD,
    RELATION_DIVERGED,
    SOURCE_REPOSITORY_PROVIDER,
    CarriedWorkSourceUnavailable,
    CommitRange,
)
from yoke_core.domain.function_target_row_project import slug_for_project_id
from yoke_core.domain.gh_rest_transport import RestRequest, request_with_retry
from yoke_core.domain.gh_rest_transport_errors import RestTransportError
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)


COMPARE_PAGE_SIZE = 100
COMPARE_PAGE_LIMIT = 10
_FULL_SHA_LENGTH = 40
# GitHub reports the head side as at or behind the base for these; both mean
# the recorded lineages do not sit on one trunk line.
_DIVERGED_STATUSES = frozenset({"behind", "diverged"})


class RepositoryProviderSource:
    """Read one project's commit graph through its authorized binding."""

    origin = SOURCE_REPOSITORY_PROVIDER

    def __init__(self, repo_slug: str, token: str) -> None:
        self._repo = repo_slug
        self._token = token
        self._graph: dict[str, dict[str, Any]] = {}
        self._warnings: list[dict[str, str]] = []
        self._unresolvable_refs = 0

    def resolve_commit(self, ref: str) -> str:
        """Resolve a full commit sha; anything else needs the commit graph.

        Release lineages are full commit shas by contract, and a lane's
        recorded head is one too. A branch name is not resolvable here without
        spending one request per candidate item, so it is reported as a
        degraded source rather than silently attributed.
        """
        token = str(ref or "").strip()
        if len(token) == _FULL_SHA_LENGTH and _is_hex(token):
            return token.lower()
        if token:
            self._unresolvable_refs += 1
        return ""

    def commit_range(self, base: str, head: str) -> CommitRange:
        status = self._load_graph(base, head)
        if status in _DIVERGED_STATUSES:
            return CommitRange(RELATION_DIVERGED, ())
        return CommitRange(RELATION_AHEAD, self._first_parent_chain(base, head))

    def commit_message(self, sha: str) -> str:
        commit = self._graph.get(sha.lower(), {})
        return str(commit.get("message") or "")

    def commit_time(self, sha: str) -> str:
        commit = self._graph.get(sha.lower(), {})
        return str(commit.get("committed_at") or "")

    def carrying_commit(
        self,
        lane_commit: str,
        *,
        base: str,
        head: str,
        commits: Sequence[str],
    ) -> str:
        """Return the range commit containing ``lane_commit``.

        The loaded graph is exactly the commits reachable from ``head`` and not
        from ``base``, so membership in it already answers both ancestry
        questions the checkout is asked: a lane commit outside the graph is
        either already released or not on this line at all.
        """
        del base, head
        lane = str(lane_commit or "").strip().lower()
        if lane not in self._graph:
            return ""
        for commit in commits:
            if self._reaches(commit, lane):
                return commit
        return ""

    def warnings(self) -> list[dict[str, str]]:
        if self._unresolvable_refs and not any(
            warning["reason"] == "lane_branch_refs_unresolvable"
            for warning in self._warnings
        ):
            self._warnings.append(
                {
                    "reason": "lane_branch_refs_unresolvable",
                    "recovery": (
                        f"{self._unresolvable_refs} lane ref(s) were branch names "
                        "rather than commit shas; attribution used recorded "
                        "evidence and commit messages instead."
                    ),
                    "error_type": "",
                }
            )
        return list(self._warnings)

    # -- graph loading -----------------------------------------------------

    def _load_graph(self, base: str, head: str) -> str:
        status = ""
        total = 0
        for page in range(1, COMPARE_PAGE_LIMIT + 1):
            body = self._compare_page(base, head, page)
            status = str(body.get("status") or "")
            total = int(body.get("total_commits") or 0)
            commits = body.get("commits")
            page_commits = list(commits) if isinstance(commits, list) else []
            for entry in page_commits:
                self._record(entry)
            if len(self._graph) >= total or not page_commits:
                break
        if len(self._graph) < total:
            raise CarriedWorkSourceUnavailable(
                "carried_range_exceeds_provider_page_limit",
                f"The comparison spans {total} commits, beyond the "
                f"{COMPARE_PAGE_LIMIT * COMPARE_PAGE_SIZE} this reader pages; "
                "record composition_resolution for this run instead.",
            )
        return status

    def _compare_page(self, base: str, head: str, page: int) -> Mapping[str, Any]:
        request = RestRequest(
            method="GET",
            path=f"/repos/{self._repo}/compare/{base}...{head}",
            query={"per_page": str(COMPARE_PAGE_SIZE), "page": str(page)},
        )
        try:
            response = request_with_retry(request, token=self._token)
        except RestTransportError as exc:
            raise CarriedWorkSourceUnavailable(
                "repository_provider_read_failed",
                "Confirm the project's GitHub binding can read repository "
                f"contents, then retry: {exc}",
            ) from exc
        body = response.body
        if not isinstance(body, Mapping):
            raise CarriedWorkSourceUnavailable(
                "repository_provider_read_failed",
                "The repository comparison returned no object; retry the "
                "derivation once the provider is healthy.",
            )
        return body

    def _record(self, entry: Any) -> None:
        if not isinstance(entry, Mapping):
            return
        sha = str(entry.get("sha") or "").strip().lower()
        if not sha:
            return
        commit = entry.get("commit")
        commit = commit if isinstance(commit, Mapping) else {}
        committer = commit.get("committer")
        committer = committer if isinstance(committer, Mapping) else {}
        parents = entry.get("parents")
        parent_shas = tuple(
            str(parent.get("sha") or "").strip().lower()
            for parent in (parents if isinstance(parents, list) else [])
            if isinstance(parent, Mapping) and parent.get("sha")
        )
        self._graph[sha] = {
            "message": str(commit.get("message") or ""),
            "committed_at": str(committer.get("date") or ""),
            "parents": parent_shas,
        }

    def _first_parent_chain(self, base: str, head: str) -> tuple[str, ...]:
        """Walk first parents from ``head`` while still inside the range.

        The graph holds exactly what is reachable from ``head`` and not from
        ``base``, which is the same stopping rule git applies for
        ``rev-list --first-parent base..head``.
        """
        del base
        chain: list[str] = []
        cursor = head.lower()
        while cursor in self._graph and cursor not in chain:
            chain.append(cursor)
            parents = self._graph[cursor]["parents"]
            cursor = parents[0] if parents else ""
        chain.reverse()
        return tuple(chain)

    def _reaches(self, start: str, target: str) -> bool:
        start = start.lower()
        target = target.lower()
        if start == target:
            return True
        seen: set[str] = set()
        stack = [start]
        while stack:
            current = stack.pop()
            if current in seen or current not in self._graph:
                continue
            seen.add(current)
            for parent in self._graph[current]["parents"]:
                if parent == target:
                    return True
                stack.append(parent)
        return False


def _is_hex(value: str) -> bool:
    try:
        int(value, 16)
    except ValueError:
        return False
    return True


def open_repository_provider_source(
    conn: Any,
    project_id: int,
) -> RepositoryProviderSource:
    """Resolve the project's own binding, or name the authority that is missing."""
    slug = slug_for_project_id(conn, int(project_id))
    try:
        auth = resolve_project_github_auth(
            slug,
            conn=conn,
            required_permissions=GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
        )
    except ProjectGithubAuthError as exc:
        raise CarriedWorkSourceUnavailable(
            "project_source_unavailable",
            "No checkout of this project is registered here and its GitHub "
            f"binding cannot read repository contents: {exc}",
        ) from exc
    return RepositoryProviderSource(auth.repo, auth.token)


__all__ = [
    "COMPARE_PAGE_LIMIT",
    "COMPARE_PAGE_SIZE",
    "RepositoryProviderSource",
    "open_repository_provider_source",
]
