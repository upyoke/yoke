"""CLI entry point for backlog mutation commands.

Imports `backlog_updates` as a module so patch-based tests and callers
resolve mutation operations through the stable write surface.
"""

from __future__ import annotations

import json
import sys
from typing import Optional

from yoke_core.domain import backlog_updates as _bu
from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id


def main(argv: Optional[list[str]] = None) -> int:
    """CLI dispatcher for backlog mutation commands."""
    args = argv if argv is not None else sys.argv[1:]

    if not args:
        print("Usage: python3 -m yoke_core.domain.backlog <command> [args...]", file=sys.stderr)
        print("Commands: create, update, structured-write", file=sys.stderr)
        return 2

    command = args[0]
    rest = args[1:]

    if command == "create":
        return _cli_create(rest)
    elif command == "update":
        return _cli_update(rest)
    elif command == "structured-write":
        return _cli_structured_write(rest)
    else:
        print(f"Unknown command: {command}", file=sys.stderr)
        return 2


def _cli_create(args: list[str]) -> int:
    title = None
    item_type = "issue"
    priority = None
    project = None
    deployment_flow = None
    status = "idea"
    source = None
    dry_run = False

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
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            return 2

    if title is None:
        print("Usage: create --title TITLE --type TYPE [--priority P] ...", file=sys.stderr)
        return 2

    result = _bu.execute_create(
        title=title,
        item_type=item_type,
        priority=priority,
        project=project,
        deployment_flow=deployment_flow,
        status=status,
        source=source,
        dry_run=dry_run,
    )
    print(json.dumps(result))
    return 0 if result.get("success") else 1


def _cli_update(args: list[str]) -> int:
    if not args:
        print("Usage: update <item-id> --field FIELD --value VALUE ...", file=sys.stderr)
        return 2

    try:
        item_id = int(args[0])
    except ValueError:
        print(f"Item ID must be an integer, got '{args[0]}'", file=sys.stderr)
        return 2

    field = None
    value = None
    done_nonce_verified = False
    force_flag = False
    qa_bypass = False
    dry_run = False

    i = 1
    while i < len(args):
        if args[i] == "--field" and i + 1 < len(args):
            field = args[i + 1]; i += 2
        elif args[i] == "--value" and i + 1 < len(args):
            value = args[i + 1]; i += 2
        elif args[i] == "--done-nonce-verified":
            done_nonce_verified = True; i += 1
        elif args[i] == "--force":
            force_flag = True; i += 1
        elif args[i] == "--qa-bypass":
            qa_bypass = True; i += 1
        elif args[i] == "--dry-run":
            dry_run = True; i += 1
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            return 2

    if field is None or value is None:
        print("Usage: update <item-id> --field FIELD --value VALUE ...", file=sys.stderr)
        return 2

    result = _bu.execute_update(
        item_id=item_id,
        field=field,
        value=value,
        done_nonce_verified=done_nonce_verified,
        force=force_flag,
        qa_bypass=qa_bypass,
        session_id=resolve_ambient_session_id(),
        dry_run=dry_run,
    )
    print(json.dumps(result))
    return 0 if result.get("success") else 1


def _cli_structured_write(args: list[str]) -> int:
    if not args:
        print("Usage: structured-write <item-id> --field FIELD (--file PATH | --stdin) ...", file=sys.stderr)
        return 2

    try:
        item_id = int(args[0])
    except ValueError:
        print(f"Item ID must be an integer, got '{args[0]}'", file=sys.stderr)
        return 2

    field = None
    file_path = None
    use_stdin = False
    force_flag = False
    source = ""

    i = 1
    while i < len(args):
        if args[i] == "--field" and i + 1 < len(args):
            field = args[i + 1]; i += 2
        elif args[i] == "--file" and i + 1 < len(args):
            file_path = args[i + 1]; i += 2
        elif args[i] == "--stdin":
            use_stdin = True; i += 1
        elif args[i] == "--force":
            force_flag = True; i += 1
        elif args[i] == "--source" and i + 1 < len(args):
            source = args[i + 1]; i += 2
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            return 2

    if field is None:
        print("Usage: structured-write <item-id> --field FIELD (--file PATH | --stdin) ...", file=sys.stderr)
        return 2

    if file_path and use_stdin:
        print(json.dumps({"success": False, "error": "cannot use both --stdin and --file; pick one"}))
        return 2

    if not file_path and not use_stdin:
        print(json.dumps({"success": False, "error": "structured field write requires --file or --stdin"}))
        return 2

    if use_stdin:
        stdin_content = sys.stdin.read()
        result = _bu.execute_structured_write(
            item_id=item_id,
            field=field,
            force=force_flag,
            source=source,
            content=stdin_content,
        )
    else:
        result = _bu.execute_structured_write(
            item_id=item_id,
            field=field,
            file_path=file_path,
            force=force_flag,
            source=source,
        )
    print(json.dumps(result))
    return 0 if result.get("success") else 1


if __name__ == "__main__":
    sys.exit(main())
