"""Board classification and next-id command handlers.

Owns the read-only commands that classify a status into its board bucket and compute
the next public ref (``PREFIX-N``) a project would issue.
"""

from __future__ import annotations

import sys

from yoke_core.domain import db_backend
from yoke_core.api.service_client_shared import (
    board,
)


def cmd_item_next_id(args: list[str]) -> int:
    """Print the next public ref a project would issue, without side effects."""
    from yoke_core.domain import backlog

    if len(args) != 1:
        print("Usage: item-next-id <project>", file=sys.stderr)
        return 2

    try:
        print(backlog.get_next_display_id(args[0]))
        return 0
    except LookupError as exc:
        print(
            f"Error: {exc}. Pass a project slug or id from `yoke projects list`.",
            file=sys.stderr,
        )
        return 2
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



__all__ = ["cmd_item_next_id", "cmd_classify_status"]
