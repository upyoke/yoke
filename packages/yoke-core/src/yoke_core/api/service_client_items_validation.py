"""Status/transition validation and next-id command handlers.

Owns the read-only commands that validate item status strings, validate
forward transitions, classify a status into its board bucket, and compute
the next-available YOK-N display id.
"""

from __future__ import annotations

import sys

from yoke_core.domain import db_backend
from yoke_core.api.service_client_shared import (
    board,
    lifecycle,
)


def cmd_item_next_id(args: list[str]) -> int:
    """Return the next available display ID without side effects."""
    from yoke_core.domain import backlog

    if args:
        print("Usage: item-next-id", file=sys.stderr)
        return 2

    try:
        print(backlog.get_next_display_id())
        return 0
    except db_backend.database_error_types() as exc:
        print(f"DB error: {exc}", file=sys.stderr)
        return 1


def cmd_classify_status(args: list[str]) -> int:
    """Map a status to its board bucket.

    Usage: classify-status <status> [--frozen 0|1] [--has-active-run 0|1] [--workflow WORKFLOW]

    Delegates to the domain board.status_to_board_bucket().
    Prints the bucket name to stdout.
    """
    if len(args) < 1:
        print("Usage: classify-status <status> [--frozen 0|1] [--has-active-run 0|1] [--workflow WORKFLOW]",
              file=sys.stderr)
        return 2

    status = args[0]
    frozen_value = None
    has_active_run = False
    workflow_id = None

    i = 1
    while i < len(args):
        if args[i] == "--frozen" and i + 1 < len(args):
            frozen_value = int(args[i + 1])
            i += 2
        elif args[i] == "--has-active-run" and i + 1 < len(args):
            has_active_run = args[i + 1] in ("1", "true", "True")
            i += 2
        elif args[i] == "--workflow" and i + 1 < len(args):
            workflow_id = args[i + 1]
            i += 2
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            return 2

    bucket = board.status_to_board_bucket(
        status=status,
        frozen_value=frozen_value,
        has_active_run=has_active_run,
        workflow_id=workflow_id,
    )
    print(bucket)
    return 0


def cmd_validate_status(args: list[str]) -> int:
    """Validate that a status string is a canonical item status.

    Usage: validate-status <status>
    Exit 0 if valid, exit 1 if not.
    """
    if len(args) < 1:
        print("Usage: validate-status <status>", file=sys.stderr)
        return 2

    if lifecycle.is_valid_item_status(args[0]):
        print("valid")
        return 0
    else:
        print(f"invalid: '{args[0]}' is not a canonical item status", file=sys.stderr)
        return 1


def cmd_validate_transition(args: list[str]) -> int:
    """Validate that a status transition is a forward progression step.

    Usage: validate-transition <from-status> <to-status> [--workflow WORKFLOW]
    Exit 0 if forward, exit 1 if not.
    When --workflow is omitted, uses the built-in epic workflow.
    """
    if len(args) < 2:
        print("Usage: validate-transition <from-status> <to-status> [--workflow WORKFLOW]", file=sys.stderr)
        return 2

    from_status = args[0]
    to_status = args[1]
    workflow_id = "epic"

    i = 2
    while i < len(args):
        if args[i] == "--workflow" and i + 1 < len(args):
            workflow_id = args[i + 1]
            i += 2
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            return 2

    from yoke_core.domain.workflow_runtime import builtin_workflow_runtime

    try:
        workflow = builtin_workflow_runtime(workflow_id)
    except KeyError:
        print(f"unknown workflow: {workflow_id}", file=sys.stderr)
        return 1
    if workflow.is_forward_transition(from_status, to_status):
        print("forward")
        return 0
    else:
        print(f"not-forward: {from_status} -> {to_status}", file=sys.stderr)
        return 1


__all__ = [
    "cmd_item_next_id",
    "cmd_classify_status",
    "cmd_validate_status",
    "cmd_validate_transition",
]
