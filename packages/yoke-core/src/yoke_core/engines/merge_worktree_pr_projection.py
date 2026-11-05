"""Reject incomplete landing reads before projecting them into gate verdicts."""

from __future__ import annotations

from typing import Any


def unreadable_landing_field(pr: dict[str, Any]) -> str | None:
    """Name a missing or malformed field; explicit nullable fields remain valid."""
    for key in (
        "merged", "closed", "state", "autoMergeRequest", "mergeQueueEntry",
        "mergeStateStatus", "headRefOid", "mergedAt", "mergeCommit", "commits",
    ):
        if key not in pr:
            return key
    for key in ("merged", "closed"):
        if not isinstance(pr[key], bool):
            return key
    for key in ("state", "mergeStateStatus", "headRefOid"):
        if not isinstance(pr[key], str) or not pr[key]:
            return key
    for key, child in (
        ("autoMergeRequest", "enabledAt"), ("mergeQueueEntry", "state"),
        ("mergeCommit", "oid"),
    ):
        value = pr[key]
        if value is not None and (
            not isinstance(value, dict) or not value.get(child)
        ):
            return f"{key}.{child}"
    commits = pr["commits"]
    if not isinstance(commits, dict) or not isinstance(commits.get("nodes"), list):
        return "commits.nodes"
    nodes = commits["nodes"]
    if len(nodes) != 1 or not isinstance(nodes[0], dict):
        return "commits.nodes.head"
    commit = nodes[0].get("commit")
    if not isinstance(commit, dict) or "statusCheckRollup" not in commit:
        return "commits.nodes.head.commit.statusCheckRollup"
    rollup = commit["statusCheckRollup"]
    if rollup is None:
        return None  # A commit with no checks has no rollup.
    if not isinstance(rollup, dict) or not isinstance(rollup.get("contexts"), dict):
        return "statusCheckRollup.contexts"
    contexts = rollup["contexts"].get("nodes")
    if not isinstance(contexts, list):
        return "statusCheckRollup.contexts.nodes"
    for node in contexts:
        if not isinstance(node, dict):
            return "statusCheckRollup.contexts.nodes.check"
        kind = node.get("__typename")
        if kind not in ("CheckRun", "StatusContext"):
            return "statusCheckRollup.contexts.nodes.__typename"
        if not isinstance(node.get("isRequired"), bool):
            return f"{kind}.isRequired"
        keys = (
            ("name", "status", "conclusion", "detailsUrl", "startedAt")
            if kind == "CheckRun"
            else ("context", "state", "targetUrl", "createdAt")
        )
        for key in keys:
            if key not in node:
                return f"{kind}.{key}"
        for key in keys[:2]:
            if not isinstance(node[key], str) or not node[key]:
                return f"{kind}.{key}"
    return None
