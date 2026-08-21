"""Shared GitHub workflow-dispatch correlation contract."""

from __future__ import annotations

import sys
from typing import Any


WORKFLOW_DISPATCH_CORRELATION_INPUT = "yoke_dispatch_id"
WORKFLOW_DISPATCH_CORRELATION_PREFIX = "yd-"
GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV = "YOKE_GITHUB_ACTIONS_LOCAL_AUTHORITY"
WORKFLOW_DISPATCH_RECOVERED_MARKER = "yoke-workflow-dispatch: recovered"
WORKFLOW_DISPATCH_DISPATCHED_MARKER = "yoke-workflow-dispatch: dispatched"


def workflow_dispatch_marker(correlation_id: str) -> str:
    """Return the exact marker exposed by a target workflow's run name."""
    return f"[yoke-dispatch:{correlation_id}]"


def workflow_dispatch_outcome_marker(dispatched: Any) -> str:
    """Stderr token naming recovered vs freshly posted dispatch, or empty."""
    if dispatched is False:
        return WORKFLOW_DISPATCH_RECOVERED_MARKER
    if dispatched is True:
        return WORKFLOW_DISPATCH_DISPATCHED_MARKER
    return ""


def print_workflow_dispatch_run(result: dict[str, Any] | None) -> None:
    """Print the run id on stdout; recovered vs dispatched on stderr."""
    payload = result or {}
    print(payload.get("run_id") or "")
    marker = workflow_dispatch_outcome_marker(payload.get("dispatched"))
    if marker:
        print(marker, file=sys.stderr)


__all__ = [
    "WORKFLOW_DISPATCH_CORRELATION_INPUT",
    "WORKFLOW_DISPATCH_CORRELATION_PREFIX",
    "GITHUB_ACTIONS_LOCAL_AUTHORITY_ENV",
    "WORKFLOW_DISPATCH_DISPATCHED_MARKER",
    "WORKFLOW_DISPATCH_RECOVERED_MARKER",
    "print_workflow_dispatch_run",
    "workflow_dispatch_marker",
    "workflow_dispatch_outcome_marker",
]
