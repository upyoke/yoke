"""What a pull request changed, read from the pull request itself.

A close-out that runs after a merge-queue landing has no local diff to
take: the merge commit is on GitHub, the head the queue merged need not
be the one this checkout holds, and a run that finds the pull request
already merged may have no lane branch left. The pull request is what
GitHub merged, so it is what the file set comes from.

Paths only, over GraphQL. The REST files listing carries every file's
patch alongside its name, which a wide branch can push past the
transport's response ceiling; this asks for the one field the landing's
file set needs. Auth and the GraphQL call itself are the merge-queue
module's, because a landing already resolves both there.
"""

from __future__ import annotations

from typing import Optional

from yoke_contracts.github_app_installation_permissions import (
    GITHUB_PULL_REQUESTS_READ_PERMISSION_LEVELS as PR_READ,
)

from yoke_core.domain.gh_rest_transport import split_repo
from yoke_core.engines.merge_worktree_pr_queue import (
    graphql_with_auth,
    resolve_auth_detail,
)
from yoke_core.engines.merge_worktree_prepare import MergeContext


_PR_FILES_QUERY = """
query($owner: String!, $name: String!, $number: Int!, $cursor: String) {
  repository(owner: $owner, name: $name) {
    pullRequest(number: $number) {
      files(first: 100, after: $cursor) {
        pageInfo { hasNextPage endCursor }
        nodes { path }
      }
    }
  }
}
"""

# GitHub returns at most 100 file nodes per page and stops listing a pull
# request's files at 3000, so a complete read is at most thirty pages.
_PR_FILES_PAGE_LIMIT = 30


def read_pr_changed_files(
    ctx: MergeContext, pr_num: str
) -> tuple[Optional[tuple[str, ...]], Optional[str]]:
    """Every path ``pr_num`` changed, in the order the listing reports.

    Returns ``(paths, None)`` — an empty tuple only when the pull request
    genuinely lists no files — or ``(None, error_detail)``.
    """
    auth, auth_err = resolve_auth_detail(ctx, PR_READ)
    if auth_err or auth is None:
        return None, auth_err
    owner, name = split_repo(auth.repo)
    try:
        number = int(str(pr_num).strip())
    except ValueError:
        return None, f"pull request reference {pr_num!r} is not a number"

    paths: list[str] = []
    cursor: Optional[str] = None
    for _page in range(_PR_FILES_PAGE_LIMIT):
        data, err = graphql_with_auth(
            auth,
            query=_PR_FILES_QUERY,
            required_permissions=PR_READ,
            variables={
                "owner": owner,
                "name": name,
                "number": number,
                "cursor": cursor,
            },
        )
        if err:
            return None, err
        pull_request = ((data or {}).get("repository") or {}).get("pullRequest") or {}
        files = pull_request.get("files")
        if not isinstance(files, dict):
            return None, (
                f"repository {owner}/{name} returned no file listing for "
                f"pull request {pr_num}"
            )
        for node in files.get("nodes") or []:
            if not isinstance(node, dict):
                continue
            path = str(node.get("path") or "")
            if path:
                paths.append(path)
        page_info = files.get("pageInfo") or {}
        cursor = str(page_info.get("endCursor") or "")
        if not page_info.get("hasNextPage") or not cursor:
            break
    return tuple(dict.fromkeys(paths)), None


__all__ = ["read_pr_changed_files"]
