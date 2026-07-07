"""Structured-field write command handler for the service_client CLI surface.

Owns ``execute-structured-write`` — the programmatic shape that writes
``spec``, ``design_spec``, ``technical_plan``, etc. and triggers body
re-render plus GitHub sync.
"""

from __future__ import annotations

import io
import json
import sys


_USAGE = (
    "Usage: execute-structured-write <item-id> --field FIELD "
    "(--file PATH | --stdin) [--force] [--source S]\n"
    "\n"
    "Positional <item-id> is the bare numeric id (e.g. 1711 — never "
    "YOK-prefixed and never a flag).\n"
    "\n"
    "Examples:\n"
    "  printf '%s' \"$content\" | python3 -m yoke_core.api.service_client \\\n"
    "      execute-structured-write 1711 --field spec --stdin\n"
    "  python3 -m yoke_core.api.service_client execute-structured-write \\\n"
    "      1711 --field technical_plan --file /tmp/plan.md --source refine\n"
)


def cmd_execute_structured_write(args: list[str]) -> int:
    """Structured field write: DB write -> render body -> sync.

    Usage: execute-structured-write <item-id> --field FIELD (--file PATH | --stdin)
                                    [--force] [--source S]

    Returns JSON result on stdout.
    """
    from yoke_core.domain import backlog

    if args and args[0] in ("-h", "--help"):
        print(_USAGE)
        return 0

    if not args:
        print(_USAGE, file=sys.stderr)
        return 2

    if args[0].startswith("-"):
        # The first positional must be the bare numeric item id. A
        # flag-first invocation with a public item ref is the
        # agent-natural shape that previously crashed with the
        # misleading ``Item ID must be integer, got '--item'`` —
        # surface the real positional shape instead.
        print(json.dumps({
            "success": False,
            "error": (
                f"execute-structured-write expects a bare numeric "
                f"item id as the first positional argument; received "
                f"flag '{args[0]}'. "
                + _USAGE.replace("\n", " ").strip()
            ),
        }))
        return 1

    try:
        item_id = int(args[0])
    except ValueError:
        print(json.dumps({
            "success": False,
            "error": (
                f"Item ID must be integer, got '{args[0]}'. "
                + _USAGE.replace("\n", " ").strip()
            ),
        }))
        return 1

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
        print(_USAGE, file=sys.stderr)
        return 2

    if file_path and use_stdin:
        print(json.dumps({"success": False, "error": "cannot use both --stdin and --file; pick one"}))
        return 2

    if not file_path and not use_stdin:
        print(json.dumps({"success": False, "error": "structured field write requires --file or --stdin"}))
        return 2

    captured = io.StringIO()
    if use_stdin:
        stdin_content = sys.stdin.read()
        result = backlog.execute_structured_write(
            item_id=item_id,
            field=field,
            force=force_flag,
            source=source,
            out=captured,
            content=stdin_content,
        )
    else:
        result = backlog.execute_structured_write(
            item_id=item_id,
            field=field,
            file_path=file_path,
            force=force_flag,
            source=source,
            out=captured,
        )
    result = dict(result)
    result["log"] = captured.getvalue()
    print(json.dumps(result))
    return 0 if result.get("success") else 1


__all__ = [
    "cmd_execute_structured_write",
]
