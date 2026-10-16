"""Capture complete agent responses through registered control-plane dispatch."""

from __future__ import annotations

import argparse
import sys

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_project_arg,
    add_session_arg,
    client_project_context,
    dispatch_and_emit,
    parse_or_usage_error,
    usage_error,
)
from yoke_cli.commands.text_file import resolve_text_file
from yoke_contracts.api.function_call import TargetRef

USAGE = (
    "yoke ouroboros reflection capture (--text-file PATH | --stdin) "
    "[--default-agent ROLE] [--project P] [--json]"
)


def reflection_capture(args: list[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke ouroboros reflection capture",
        description=USAGE,
        epilog="Retain the response text until capture succeeds. On an older "
        "server, ask the control-plane operator to serve the carrying release; "
        "do not switch to a database connection.",
    )
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--text-file")
    source.add_argument("--stdin", action="store_true")
    parser.add_argument("--default-agent", default="unknown")
    add_project_arg(parser)
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, USAGE)
    if parsed is None:
        return 2
    project = client_project_context(parsed.project)
    if not project:
        return usage_error(
            "project_required: pass --project P or use a registered checkout"
        )
    try:
        text = (
            sys.stdin.read()
            if parsed.stdin
            else resolve_text_file(
                None,
                parsed.text_file,
                "--text-file",
            )
        )
    except (OSError, ValueError) as exc:
        return usage_error(
            f"reflection_input_unavailable: {exc}; retain and pass a readable response file"
        )
    return dispatch_and_emit(
        function_id="ouroboros.reflection.capture",
        target=TargetRef(kind="global", project_id=project),
        payload={"text": text, "default_agent": parsed.default_agent},
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )
