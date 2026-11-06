"""Keep a declared park through a turn that only receives Fleet mail.

The durable mode and reason remain the park's owner while the turn runs.
Successful work ends that wait; prompts, failed calls and message receipts
do not. An explicit sessions touch owns its own mode change.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.hook_runner.shell_parse import parse_shell
from yoke_core.domain.lint_command_extract import extract_command
from yoke_core.domain.lint_session_cwd_host_command import yoke_subcommand_positionals
from yoke_core.domain.session_mode import clear_parked_mode


def unpark_after_work(conn: Any, envelope: dict[str, Any]) -> bool:
    """Clear a park only for successful activity beyond receiving messages."""
    detail = (envelope.get("context") or {}).get("detail") or {}
    tool_input = detail.get("tool_input")
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (ValueError, TypeError):
            tool_input = {"command": tool_input}
    command = extract_command({"tool_input": tool_input})
    if command:
        parsed = parse_shell(command)
        quiet = {
            ("messages", "get"),
            ("messages", "acknowledge"),
            ("messages", "list"),
            ("sessions", "touch"),
        }
        if (
            parsed.segments
            and not parsed.unparsed
            and all(
                segment.program == "yoke"
                and (
                    tuple(yoke_subcommand_positionals(segment.argv, limit=2)) in quiet
                    or tuple(yoke_subcommand_positionals(segment.argv, limit=3))
                    == ("sessions", "wake", "schedule")
                )
                for segment in parsed.segments
            )
        ):
            return False
    return clear_parked_mode(conn, str(envelope["session_id"]))
