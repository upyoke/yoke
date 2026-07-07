"""Item-creation command handlers for the service_client CLI surface.

Owns ``execute-create`` (programmatic) and ``execute-create-cli`` (the public
``backlog-registry add`` shape).
"""

from __future__ import annotations

import io
import json
import os
import sys

from yoke_core.api.service_client_shared import (
    _emit_backlog_result,
    _isolated_test_mutation_error,
)


def cmd_execute_create(args: list[str]) -> int:
    """Full item creation: validate -> INSERT -> md gen -> GitHub sync.

    Usage: execute-create --title TITLE --type TYPE [--priority P]
                          [--project P] [--deployment-flow F] [--status S]
                          [--source S] [--dry-run] [--idea-intake]

    Returns JSON result on stdout. ``--idea-intake`` carries the
    sanctioned-idea-intake provenance signal (equivalent to the
    ``YOKE_IDEA_INTAKE`` env var). The idea skill passes either.
    """
    from yoke_core.domain import backlog

    title = None
    item_type = "issue"
    priority = None
    project = None
    deployment_flow = None
    status = "idea"
    source = None
    dry_run = False
    provenance = None

    i = 0
    while i < len(args):
        if args[i] == "--title" and i + 1 < len(args):
            title = args[i + 1]; i += 2
        elif args[i] == "--type" and i + 1 < len(args):
            item_type = args[i + 1]; i += 2
        elif args[i] == "--priority" and i + 1 < len(args):
            priority = args[i + 1]; i += 2
        elif args[i] == "--project" and i + 1 < len(args):
            project = args[i + 1]; i += 2
        elif args[i] == "--deployment-flow" and i + 1 < len(args):
            deployment_flow = args[i + 1]; i += 2
        elif args[i] == "--status" and i + 1 < len(args):
            status = args[i + 1]; i += 2
        elif args[i] == "--source" and i + 1 < len(args):
            source = args[i + 1]; i += 2
        elif args[i] == "--dry-run":
            dry_run = True; i += 1
        elif args[i] == "--idea-intake":
            provenance = "idea"; i += 1
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            return 2

    if title is None:
        print("Usage: execute-create --title TITLE --type TYPE ...", file=sys.stderr)
        return 2

    captured = io.StringIO()
    result = backlog.execute_create(
        title=title,
        item_type=item_type,
        priority=priority,
        project=project,
        deployment_flow=deployment_flow,
        status=status,
        source=source,
        session_id=os.environ.get("YOKE_SESSION_ID"),
        dry_run=dry_run,
        provenance=provenance,
        out=captured,
    )
    result = dict(result)
    result["log"] = captured.getvalue()
    print(json.dumps(result))
    return 0 if result.get("success") else 1


def cmd_execute_create_cli(args: list[str]) -> int:
    """Parse the public backlog-registry add CLI shape in Python."""
    from yoke_core.domain import backlog

    isolation_error = _isolated_test_mutation_error()
    if isolation_error:
        return _emit_backlog_result({"success": False, "error": isolation_error})

    dry_run = False
    project = None
    deployment_flow = None
    provenance = None
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--dry-run":
            dry_run = True
            i += 1
        elif token == "--project" and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        elif token == "--deployment-flow" and i + 1 < len(args):
            deployment_flow = args[i + 1]
            i += 2
        elif token == "--idea-intake":
            provenance = "idea"
            i += 1
        else:
            break

    positional = args[i:]
    if len(positional) > 4:
        return _emit_backlog_result(
            {
                "success": False,
                "error": (
                    "item epic links are retired; backlog-cli add "
                    "no longer accepts a parent epic argument."
                ),
            }
        )

    if len(positional) < 2:
        print(
            "Usage: execute-create-cli [--dry-run] [--project P] [--deployment-flow F] "
            "<title> <type> [status] [priority]",
            file=sys.stderr,
        )
        return 2

    title = positional[0]
    item_type = positional[1]
    status = positional[2] if len(positional) >= 3 else "idea"
    priority = positional[3] if len(positional) >= 4 else None

    captured = io.StringIO()
    result = backlog.execute_create(
        title=title,
        item_type=item_type,
        priority=priority,
        project=project,
        deployment_flow=deployment_flow,
        status=status,
        session_id=os.environ.get("YOKE_SESSION_ID"),
        dry_run=dry_run,
        rebuild_board=True,
        provenance=provenance,
        out=captured,
    )
    return _emit_backlog_result(dict(result), log=captured.getvalue())


__all__ = [
    "cmd_execute_create",
    "cmd_execute_create_cli",
]
