"""Batch ancestry and commit facts from one git pass over a checkout.

Containment used to ask ``merge-base --is-ancestor`` once per candidate
commit. Individual calls are milliseconds; a release carrying many
delivery-ready items paid that cost thousands of times. One
``rev-list --parents`` of the candidate tip is the same graph, and the
honest/unknown distinctions stay the walker's: a missing tip yields an
empty graph, which is the same definite no ``is-ancestor`` returned when
git could not resolve the objects.
"""

from __future__ import annotations

from typing import Iterable, Sequence

from yoke_core.domain import standalone_item_merge_git as git


def parent_graph(repo_root: str, tip: str) -> dict[str, tuple[str, ...]]:
    """Return every commit reachable from ``tip``, mapped to its parents.

    One subprocess. An unreadable tip yields an empty graph rather than
    raising, matching :func:`git.is_ancestor`'s soft failure.
    """
    if not tip:
        return {}
    listing = git.git_out(repo_root, "rev-list", "--parents", tip)
    graph: dict[str, tuple[str, ...]] = {}
    for line in listing.splitlines():
        parts = line.split()
        if parts:
            graph[parts[0]] = tuple(parts[1:])
    return graph


def commit_is_ancestor(
    graph: dict[str, tuple[str, ...]], candidate: str, commit: str
) -> bool:
    """Whether ``candidate``'s history already holds ``commit``."""
    if not candidate or not commit:
        return False
    if candidate == commit:
        return True
    seen: dict[str, bool] = {}

    def reachable(node: str) -> bool:
        if node == commit:
            return True
        cached = seen.get(node)
        if cached is not None:
            return cached
        seen[node] = False
        result = any(reachable(parent) for parent in graph.get(node, ()))
        seen[node] = result
        return result

    return reachable(candidate)


def carrying_commit(
    graph: dict[str, tuple[str, ...]],
    lane_commit: str,
    *,
    base: str,
    head: str,
    commits: Sequence[str],
) -> str:
    """Return the first range commit that contains ``lane_commit``, or ``""``.

    The verdicts match the per-commit ``is-ancestor`` walk: already in
    ``base`` is not this range, missing from ``head`` is not on this line,
    and the earliest listed range commit that contains the lane is the
    carrier.
    """
    if not lane_commit:
        return ""
    if commit_is_ancestor(graph, base, lane_commit):
        return ""
    if not commit_is_ancestor(graph, head, lane_commit):
        return ""
    for commit in commits:
        if commit_is_ancestor(graph, commit, lane_commit):
            return commit
    return ""


def commit_facts(
    repo_root: str, shas: Iterable[str]
) -> dict[str, tuple[str, str]]:
    """Return ``sha -> (committer ISO time, message)`` in one ``git log``.

    A failed read yields an empty map, matching per-sha ``git show``
    returning empty strings.
    """
    unique = tuple(dict.fromkeys(sha for sha in shas if sha))
    if not unique:
        return {}
    raw = git.git_out(
        repo_root,
        "log",
        "--no-walk",
        "--format=%H%x00%cI%x00%B%x00",
        *unique,
    )
    facts: dict[str, tuple[str, str]] = {}
    parts = raw.split("\0")
    index = 0
    while index + 2 < len(parts):
        sha, when, message = parts[index], parts[index + 1], parts[index + 2]
        if sha:
            facts[sha] = (when, message.rstrip("\n"))
        index += 3
    return facts


__all__ = [
    "carrying_commit",
    "commit_facts",
    "commit_is_ancestor",
    "parent_graph",
]
