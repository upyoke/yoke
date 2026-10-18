"""Bind consumer workflow source to an immutable commit through a guarded tag."""

from __future__ import annotations

import json
from typing import Callable


def consumer_dispatch_tag(sha: str) -> str:
    """The create-only tag that pins consumer workflow source to *sha*."""
    return f"yoke-deploy/consumer-{sha}"


def bound_dispatch_ref(
    run_yoke: Callable,
    *,
    repo: str,
    project: str,
    sha: str,
    timeout: int,
) -> tuple[str, str]:
    """Ensure an exact-commit tag and require its identity receipt before dispatch."""
    tag = consumer_dispatch_tag(sha)
    code, stdout, stderr = run_yoke(
        [
            "github-actions",
            "dispatch-tag",
            "ensure",
            repo,
            tag,
            sha,
            "--project",
            project,
            "--json",
        ],
        timeout=timeout,
    )
    if code:
        return "", (
            "consumer_dispatch_ref_unavailable: "
            f"{stderr.strip() or stdout.strip() or 'no receipt'}. "
            "Restore the consumer project's contents-write authority or the "
            "served dispatch-tag command, then retry this exact pair."
        )
    try:
        payload = json.loads(stdout)
        result = payload["result"]
        if payload["success"] and all(
            result.get(key) == value
            for key, value in (("repo", repo), ("tag", tag), ("sha", sha))
        ):
            return tag, ""
    except (ValueError, KeyError, TypeError, AttributeError):
        pass
    return "", (
        "consumer_dispatch_ref_unverified: tag receipt did not name the bound "
        f"consumer commit {sha}. Repair dispatch-tag receipt delivery, then "
        "retry this pair; no workflow was dispatched."
    )
