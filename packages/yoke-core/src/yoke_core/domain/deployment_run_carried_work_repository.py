"""Answer a project's commit comparison over its own repository provider.

A control plane serving an HTTPS-only project holds no checkout of that
project, so the comparison runs over the binding the project already
authorized. The comparison supplies each commit's parents, message, author,
and time; the first-parent range is walked out of that graph.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Mapping, Optional, Sequence

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_CONTENTS_READ_PERMISSION_LEVELS,
)
from yoke_core.domain.commit_evidence_instant import commit_instant
from yoke_core.domain.deployment_run_compare_graph import CompareGraph
from yoke_core.domain.deployment_run_carried_work_source import (
    RELATION_AHEAD,
    RELATION_DIVERGED,
    SOURCE_REPOSITORY_PROVIDER,
    CarriedWorkSourceUnavailable,
    CommitRange,
)
from yoke_core.domain.deployment_run_compare_response import (
    FULL_SHA_LENGTH,
    base_contains_head,
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
from yoke_core.domain.gh_rest_transport_errors import (
    RestNotFoundError,
    RestTransportError,
)
from yoke_core.domain.repository_provider_refusal import (
    head_unpublished,
    read_failed,
    unreadable_body,
)
from yoke_core.domain.project_github_auth import (
    ProjectGithubAuthError,
    resolve_project_github_auth,
)
from yoke_core.domain.repository_compare_pages import compare_page
from yoke_core.domain.repository_content_equivalence import (
    blob_sha,
    content_already_present,
)

COMPARE_PAGE_SIZE = 100
COMPARE_PAGE_LIMIT = 10
#: Refs resolved through their own request: containment asks two, attribution
#: one lane ref per item, so a large backlog never becomes a request per item.
COMMIT_LOOKUP_BUDGET = 8


class RepositoryProviderSource:
    """Read one project's commit graph through its authorized binding."""

    origin = SOURCE_REPOSITORY_PROVIDER

    def __init__(self, repo_slug: str, token: str) -> None:
        self.location = repo_slug
        self._token = token
        self._graphs: dict[tuple[str, str], CompareGraph] = {}
        self._warnings: list[dict[str, str]] = []
        self._resolved_refs: dict[str, str] = {}
        self._compare_statuses: dict[tuple[str, str], str] = {}
        self._compare_pages: dict[tuple[str, str, int], Mapping[str, Any]] = {}
        self._lookups = 0
        self._unresolvable_refs = 0

    def resolve_commit(self, ref: str) -> str:
        """Return the full object id ``ref`` names, or ``""``.

        A full sha needs no request. Anything else — an abbreviated sha, a
        branch, a tag — is resolved by the provider rather than padded into a
        hash that matches nothing. Resolutions are cached and budgeted, and an
        exhausted budget is reported as a degraded source, never dropped.
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

    def resolve_commits(self, refs: Sequence[str]) -> dict[str, str]:
        return {ref: self.resolve_commit(ref) for ref in refs}

    def _commit_sha(self, ref: str) -> str:
        """Ask the provider for one ref's commit, answering "" when it has none."""
        request = RestRequest(
            method="GET",
            path=f"/repos/{self.location}/commits/{ref}",
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

    def contains_commit(self, candidate: str, commit: str) -> Optional[bool]:
        """Read ancestry from the candidate's own, cheap side of the compare."""
        return base_contains_head(
            require_status(self._compare_page(candidate, commit, 1))
        )

    def adds_nothing(self, candidate: str, commit: str) -> Optional[bool]:
        """Answer the merge boundary's content question over the provider."""
        return content_already_present(
            self._compare_page(candidate, commit, 1),
            lambda path: blob_sha(self.location, self._token, path, candidate),
        )

    def commit_range(self, base: str, head: str) -> CommitRange:
        status = self._load_graph(base, head)
        if relation(status) == RELATION_DIVERGED:
            return CommitRange(RELATION_DIVERGED, ())
        return CommitRange(
            RELATION_AHEAD, self._graphs[(base, head)].first_parent_chain(head)
        )

    def _compare_status(self, base: str, head: str) -> str:
        cached = self._compare_statuses.get((base, head))
        if cached is not None:
            return cached
        status = require_status(self._compare_page(base, head, 1))
        self._compare_statuses[(base, head)] = status
        return status

    def _commit(self, sha: str) -> Mapping[str, Any]:
        """A commit's own facts are the same in every comparison listing it."""
        for graph in self._graphs.values():
            if sha.lower() in graph:
                return graph.commits[sha.lower()]
        return {}

    def commit_message(self, sha: str) -> str:
        return str(self._commit(sha).get("message") or "")

    def commit_time(self, sha: str) -> datetime | None:
        return commit_instant(self._commit(sha).get("committed_at"))

    def commit_author(self, sha: str) -> str:
        return str(self._commit(sha).get("author") or "")

    def carrying_commit(
        self,
        lane_commit: str,
        *,
        base: str,
        head: str,
        commits: Sequence[str],
    ) -> str:
        """Return the range commit containing ``lane_commit``.

        The pair's graph is exactly the commits reachable from ``head`` and
        not from ``base``, so membership in it already answers both ancestry
        questions the checkout is asked: a lane commit outside the graph is
        either already released or not on this line at all.
        """
        graph = self._graphs.get((base, head))
        lane = str(lane_commit or "").strip().lower()
        if graph is None or lane not in graph:
            return ""
        for commit in commits:
            if graph.reaches(commit, lane):
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
                        "lookups; attribution used recorded evidence instead."
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
        exists to avoid. Only this pair's own listing is counted.
        """
        status = ""
        total = 0
        graph = CompareGraph()
        for page in range(1, COMPARE_PAGE_LIMIT + 1):
            body = self._compare_page(base, head, page)
            status = require_status(body)
            total = require_total(body)
            page_commits = require_commits(body)
            for entry in page_commits:
                graph.add(recorded_commit(entry))
            if len(graph) >= total or not page_commits:
                break
        if len(graph) != total:
            raise incomplete(
                f"the comparison declares {total} commit(s) and this reader "
                f"holds {len(graph)} after paging up to "
                f"{COMPARE_PAGE_LIMIT * COMPARE_PAGE_SIZE}"
            )
        self._graphs[(base, head)] = graph
        self._compare_statuses[(base, head)] = status
        return status

    def _compare_page(self, base: str, head: str, page: int) -> Mapping[str, Any]:
        """Read one comparison page, serving a page already read.

        Containment asks one page two questions — ancestry from its status,
        content from its file listing — so the cache keeps that one read.

        Refusals are named in :mod:`repository_provider_refusal`.
        """
        cached = self._compare_pages.get((base, head, page))
        if cached is not None:
            return cached
        body = compare_page(
            self.location, base, head, page, lambda: self._read_page(base, head, page)
        )
        self._compare_pages[(base, head, page)] = body
        return body

    def _read_page(self, base: str, head: str, page: int) -> Mapping[str, Any]:
        request = RestRequest(
            method="GET",
            path=f"/repos/{self.location}/compare/{base}...{head}",
            query={"per_page": str(COMPARE_PAGE_SIZE), "page": str(page)},
        )
        try:
            response = request_with_retry(request, token=self._token)
        except RestNotFoundError as exc:
            # The provider answered: it does not hold one of these commits.
            raise head_unpublished(self.location, base, head) from exc
        except RestTransportError as exc:
            # One summary code cannot separate a rate limit from a revoked
            # permission from a 502; the transport already classified it.
            raise read_failed(exc) from exc
        body = response.body
        if not isinstance(body, Mapping):
            raise unreadable_body()
        return body


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
