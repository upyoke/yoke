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
from yoke_core.domain.deployment_run_compare_response import (
    FULL_SHA_LENGTH,
    incomplete,
    is_hex,
    recorded_commit,
    relation,
    require_commits,
    require_status,
    require_total,
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
#: How many refs may be resolved through their own request. Containment asks
#: for two, while commit attribution can offer one lane ref per item, so the
#: budget keeps a large backlog from becoming a request per item.
COMMIT_LOOKUP_BUDGET = 8


class RepositoryProviderSource:
    """Read one project's commit graph through its authorized binding."""

    origin = SOURCE_REPOSITORY_PROVIDER

    def __init__(self, repo_slug: str, token: str) -> None:
        self._repo = repo_slug
        self._token = token
        self._graph: dict[str, dict[str, Any]] = {}
        self._warnings: list[dict[str, str]] = []
        self._resolved_refs: dict[str, str] = {}
        self._compare_statuses: dict[tuple[str, str], str] = {}
        self._lookups = 0
        self._unresolvable_refs = 0

    def resolve_commit(self, ref: str) -> str:
        """Return the full object id ``ref`` names, or ``""``.

        A full sha needs no request. Anything else — an abbreviated sha, a
        branch, a tag — is resolved by the provider rather than padded into a
        hash that matches nothing, which is the failure a prefix comparison
        produces silently. Resolutions are cached and budgeted, and exhausting
        the budget is reported as a degraded source instead of quietly
        dropping the attribution it would have supplied.
        """
        token = str(ref or "").strip()
        if not token:
            return ""
        if len(token) == FULL_SHA_LENGTH and is_hex(token):
            return token.lower()
        if token in self._resolved_refs:
            return self._resolved_refs[token]
        if self._lookups >= COMMIT_LOOKUP_BUDGET:
            self._unresolvable_refs += 1
            return ""
        self._lookups += 1
        resolved = self._commit_sha(token)
        self._resolved_refs[token] = resolved
        if not resolved:
            self._unresolvable_refs += 1
        return resolved

    def _commit_sha(self, ref: str) -> str:
        """Ask the provider for one ref's commit, answering "" when it has none."""
        request = RestRequest(
            method="GET",
            path=f"/repos/{self._repo}/commits/{ref}",
        )
        try:
            response = request_with_retry(request, token=self._token)
        except RestTransportError:
            return ""
        body = response.body
        if not isinstance(body, Mapping):
            return ""
        sha = str(body.get("sha") or "").strip().lower()
        return sha if len(sha) == FULL_SHA_LENGTH and is_hex(sha) else ""

    def lineage_relation(self, base: str, head: str) -> str:
        """Answer ancestry from the comparison's own status.

        Ancestry is one field, so it is read from the first page alone: a
        comparison spanning more commits than this reader pages is still a
        truthful ancestry answer, and blocking it on the listing would refuse
        exactly the long-lived repositories that need it most.
        """
        return relation(self._compare_status(base, head))

    def commit_range(self, base: str, head: str) -> CommitRange:
        status = self._load_graph(base, head)
        if relation(status) == RELATION_DIVERGED:
            return CommitRange(RELATION_DIVERGED, ())
        return CommitRange(RELATION_AHEAD, self._first_parent_chain(base, head))

    def _compare_status(self, base: str, head: str) -> str:
        cached = self._compare_statuses.get((base, head))
        if cached is not None:
            return cached
        status = require_status(self._compare_page(base, head, 1))
        self._compare_statuses[(base, head)] = status
        return status

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
                        f"{self._unresolvable_refs} lane ref(s) named no commit "
                        f"the provider could resolve within {COMMIT_LOOKUP_BUDGET} "
                        "lookups; attribution used recorded evidence and commit "
                        "messages instead."
                    ),
                    "error_type": "",
                }
            )
        return list(self._warnings)

    # -- graph loading -----------------------------------------------------

    def _load_graph(self, base: str, head: str) -> str:
        """Page the full commit listing, refusing an incomplete comparison.

        Every structural gap here is a reason to answer "unknown" rather than
        "empty": a body with no commit total, no listing, or fewer commits
        than it declares has not told this reader what the range holds, and
        recording that as an empty release is the exact confusion carried work
        exists to avoid.
        """
        status = ""
        total = 0
        for page in range(1, COMPARE_PAGE_LIMIT + 1):
            body = self._compare_page(base, head, page)
            status = require_status(body)
            total = require_total(body)
            page_commits = require_commits(body)
            for entry in page_commits:
                self._graph.update(recorded_commit(entry))
            if len(self._graph) >= total or not page_commits:
                break
        if len(self._graph) != total:
            raise incomplete(
                f"the comparison declares {total} commit(s) and this reader "
                f"holds {len(self._graph)} after paging up to "
                f"{COMPARE_PAGE_LIMIT * COMPARE_PAGE_SIZE}"
            )
        self._compare_statuses[(base, head)] = status
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

    def _first_parent_chain(self, base: str, head: str) -> tuple[str, ...]:
        """Walk first parents from ``head`` while still inside the range.

        The graph holds exactly what is reachable from ``head`` and not from
        ``base``, which is the same stopping rule git applies for
        ``rev-list --first-parent base..head``. The walk therefore has to
        start at ``head``: a non-empty comparison whose listing does not
        contain the commit it was asked about describes some other range, and
        walking it would report an empty release rather than an unread one.
        """
        del base
        chain: list[str] = []
        cursor = head.lower()
        if not self._graph:
            return ()
        if cursor not in self._graph:
            raise incomplete(
                f"the comparison listed {len(self._graph)} commit(s) but not "
                f"{cursor}, the head it was asked about"
            )
        while cursor in self._graph and cursor not in chain:
            chain.append(cursor)
            # ``recorded_commit`` refuses an unreadable parent, so leaving
            # the graph is the only way this walk ends: the base side.
            cursor = self._graph[cursor]["parents"][0]
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
    "COMMIT_LOOKUP_BUDGET",
    "COMPARE_PAGE_LIMIT",
    "COMPARE_PAGE_SIZE",
    "RepositoryProviderSource",
    "open_repository_provider_source",
]
