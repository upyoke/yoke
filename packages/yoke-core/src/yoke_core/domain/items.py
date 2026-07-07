"""Item CRUD helpers and CLI for the ``items`` table in the Yoke DB.

Provides stable importable query/write helpers plus the module CLI used by the
DB router and operator-facing item surfaces.

Library usage::

    from yoke_core.domain.items import query_item, query_item_row, insert_item

CLI usage::

    python3 -m yoke_core.domain.items <subcmd> [args...]

Subcommands:

    get <id> <field>
    row <id>
    insert --id N --title T ...
    update <id> <field> <value>
    update-multi <id> field1=val1 ...
    update-structured <id> <field> (--body-file <path> | --stdin) [--force] [--source S]
    list [--status S] [--type T] [--priority P]

Exit codes: 0 success, 1 error/not-found, 2 usage error.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, Optional, Sequence

# Public façade: callers import stable names from ``yoke_core.domain.items``
# while implementations live in responsibility-specific siblings.
from yoke_core.domain.items_constants import (
    CANONICAL_COLUMNS,
    CONTENT_FIELDS,
    DEFAULT_ITEM_ACTOR_ID,
    INTEGER_FIELDS,
    LARGE_TEXT_FIELDS,
    LIST_COLUMNS,
    STRUCTURED_FIELDS,
)
from yoke_core.domain.items_queries import (
    query_item,
    query_item_row,
    query_items_list,
)
from yoke_core.domain.items_writes import (
    insert_item,
    update_item_field,
    update_item_multi,
    update_structured_field,
)

__all__ = [
    "CANONICAL_COLUMNS",
    "CONTENT_FIELDS",
    "INTEGER_FIELDS",
    "LARGE_TEXT_FIELDS",
    "LIST_COLUMNS",
    "STRUCTURED_FIELDS",
    "query_item",
    "query_item_row",
    "query_items_list",
    "insert_item",
    "update_item_field",
    "update_item_multi",
    "update_structured_field",
    "main",
]


# ---------------------------------------------------------------------------
# CLI entry point
# ---------------------------------------------------------------------------

def _build_parser() -> argparse.ArgumentParser:
    """Build the CLI argument parser."""
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.domain.items",
        description="Item CRUD for the Yoke DB",
    )
    sub = parser.add_subparsers(dest="command")

    # get <id> <field>
    p_get = sub.add_parser("get", help="Query single item field")
    p_get.add_argument("id", type=int, help="Item ID (numeric)")
    p_get.add_argument("field", help="Column name to read")

    # row <id>
    p_row = sub.add_parser("row", help="Query full item row (pipe-delimited)")
    p_row.add_argument("id", type=int, help="Item ID (numeric)")

    # insert
    p_ins = sub.add_parser("insert", help="Insert a new item")
    p_ins.add_argument("--id", type=int, required=True, help="Item ID")
    p_ins.add_argument("--title", default=None)
    p_ins.add_argument("--type", dest="item_type", default=None)
    p_ins.add_argument("--status", default=None)
    p_ins.add_argument("--priority", default=None)
    p_ins.add_argument("--flow", default=None)
    p_ins.add_argument("--rework-count", type=int, default=None)
    p_ins.add_argument("--frozen", type=int, default=None)
    p_ins.add_argument("--blocked", type=int, default=None)
    p_ins.add_argument("--blocked-reason", default=None)
    p_ins.add_argument("--github-issue", default=None)
    p_ins.add_argument("--deployed-to", default=None)
    p_ins.add_argument("--worktree", default=None)
    p_ins.add_argument("--body", default=None)
    p_ins.add_argument("--body-file", default=None, help="Read body from file")
    p_ins.add_argument("--created-at", default=None)
    p_ins.add_argument("--updated-at", default=None)
    p_ins.add_argument("--source", default=DEFAULT_ITEM_ACTOR_ID)
    p_ins.add_argument("--project", default=None)
    p_ins.add_argument("--deployment-flow", default=None)

    # update <id> <field> <value>
    p_upd = sub.add_parser("update", help="Update single non-structured field")
    p_upd.add_argument("id", type=int, help="Item ID (numeric)")
    p_upd.add_argument("field", help="Column name to update")
    p_upd.add_argument("value", help="New value (use 'null' for NULL)")

    # update-multi <id> field1=val1 ...
    p_multi = sub.add_parser("update-multi", help="Batch update multiple fields")
    p_multi.add_argument("id", type=int, help="Item ID (numeric)")
    p_multi.add_argument("pairs", nargs="+", help="field=value pairs")

    # update-structured <id> <field> (--body-file <path> | --stdin) [--force] [--source S]
    p_struct = sub.add_parser("update-structured", help="Update structured text field")
    p_struct.add_argument("id", type=int, help="Item ID (numeric)")
    p_struct.add_argument("field", help="Structured field name")
    p_struct.add_argument("--body-file", default=None, help="Path to content file")
    p_struct.add_argument("--stdin", action="store_true", dest="use_stdin", help="Read content from stdin")
    p_struct.add_argument("--force", action="store_true", help="Bypass shrinkage guard")
    p_struct.add_argument("--source", default="", help="Source name for tracking")

    # list [--status S] [--type T] [--priority P]
    p_list = sub.add_parser("list", help="Filtered item list")
    p_list.add_argument("--status", default=None)
    p_list.add_argument("--type", dest="item_type", default=None)
    p_list.add_argument("--priority", default=None)

    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    """CLI entry point. Returns exit code."""
    parser = _build_parser()
    args = parser.parse_args(argv)

    if not args.command:
        parser.print_help(sys.stderr)
        return 2

    try:
        if args.command == "get":
            result = query_item(args.id, args.field)
            print(result)
            return 0

        elif args.command == "row":
            result = query_item_row(args.id)
            if result is None:
                print(f"Error: item {args.id} not found", file=sys.stderr)
                return 1
            print(result)
            return 0

        elif args.command == "insert":
            body = args.body
            if args.body_file:
                body = Path(args.body_file).read_text(encoding="utf-8")
            # Build kwargs, omitting None values so function defaults apply
            kwargs: Dict[str, Any] = {"item_id": args.id}
            _cli_field_map = {
                "title": args.title, "item_type": args.item_type,
                "status": args.status, "priority": args.priority,
                "flow": args.flow, "rework_count": args.rework_count,
                "frozen": args.frozen,
                "blocked": args.blocked, "blocked_reason": args.blocked_reason,
                "github_issue": args.github_issue,
                "deployed_to": args.deployed_to, "worktree": args.worktree,
                "body": body, "created_at": args.created_at,
                "updated_at": args.updated_at, "source": args.source,
                "project": args.project, "deployment_flow": args.deployment_flow,
            }
            for k, v in _cli_field_map.items():
                if v is not None:
                    kwargs[k] = v
            insert_item(**kwargs)
            return 0

        elif args.command == "update":
            update_item_field(args.id, args.field, args.value)
            return 0

        elif args.command == "update-multi":
            pairs: Dict[str, str] = {}
            for pair in args.pairs:
                if "=" not in pair:
                    print(
                        f"Error: invalid pair '{pair}' (expected field=value)",
                        file=sys.stderr,
                    )
                    return 2
                key, _, val = pair.partition("=")
                pairs[key] = val
            update_item_multi(args.id, pairs)
            return 0

        elif args.command == "update-structured":
            if args.body_file and args.use_stdin:
                print(
                    json.dumps({"success": False, "error": "cannot use both --stdin and --body-file; pick one"}),
                    file=sys.stderr,
                )
                return 2
            if not args.body_file and not args.use_stdin:
                print(
                    json.dumps({"success": False, "error": "structured field write requires --body-file or --stdin"}),
                    file=sys.stderr,
                )
                return 2
            if args.use_stdin:
                content = sys.stdin.read()
            else:
                content = Path(args.body_file).read_text(encoding="utf-8")
            update_structured_field(
                item_id=args.id,
                field=args.field,
                content=content,
                force=args.force,
                source=args.source,
            )
            return 0

        elif args.command == "list":
            result = query_items_list(
                status=args.status,
                item_type=args.item_type,
                priority=args.priority,
            )
            if result:
                print(result)
            return 0

        else:
            parser.print_help(sys.stderr)
            return 2

    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except Exception as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
