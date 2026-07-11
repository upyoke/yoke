"""Shared GitHub workflow-dispatch correlation contract."""

from __future__ import annotations


WORKFLOW_DISPATCH_CORRELATION_INPUT = "yoke_dispatch_id"
WORKFLOW_DISPATCH_CORRELATION_PREFIX = "yd-"
GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV = "YOKE_GITHUB_ACTIONS_LOCAL_AUTHORITY"


def workflow_dispatch_marker(correlation_id: str) -> str:
    """Return the exact marker exposed by a target workflow's run name."""
    return f"[yoke-dispatch:{correlation_id}]"


__all__ = [
    "WORKFLOW_DISPATCH_CORRELATION_INPUT",
    "WORKFLOW_DISPATCH_CORRELATION_PREFIX",
    "GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV",
    "workflow_dispatch_marker",
]
