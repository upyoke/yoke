"""Keep a declared park through a turn that only reads or keeps the books.

The durable mode and reason remain the park's owner while the turn runs.
Successful work ends that wait; prompts, failed calls, message receipts and
read-only activity do not. Read-only activity is a harness read tool
(Read, Grep, Glob), read-only Git inspection, or a ``yoke`` command whose
registered function is a read (``READ_COMMAND_ROUTES``, generated from
the CLI and function registries). A shell call stays quiet only when every
segment is one of those, a bookkeeping command, or a plain ``cd``; a
redirect or substitution makes it work. An explicit sessions touch owns its own mode change.
"""

from __future__ import annotations

import json
from typing import Any

from yoke_contracts.hook_runner.shell_parse import ShellSegment, parse_shell
from yoke_contracts.hook_tool_names import canonical_tool_name
from yoke_contracts.registered_reads import READ_COMMAND_ROUTES
from yoke_core.domain.lint_command_extract import extract_command
from yoke_core.domain.lint_session_cwd_foreign_lane import is_read_only_git_inspection
from yoke_core.domain.lint_session_cwd_host_command import yoke_subcommand_positionals
from yoke_core.domain.session_mode import clear_parked_mode

# Harness tools that only read files (chain vocabulary names).
_READ_TOOLS = frozenset({"Read", "Grep", "Glob"})
# Bookkeeping that writes, but only to keep the parked wait itself current.
_BOOKKEEPING = frozenset(
    {
        ("messages", "acknowledge"),
        ("messages", "ack"),
        ("items", "progress-log", "append"),
        ("sessions", "touch"),
        ("sessions", "wake", "schedule"),
    }
)
_QUIET_ROUTES = READ_COMMAND_ROUTES | _BOOKKEEPING
_ROUTE_WORDS = max(len(route) for route in _QUIET_ROUTES)
_SHELL_WRITES = (">", "$(", "`")


def _quiet_yoke(segment: ShellSegment) -> bool:
    words = tuple(yoke_subcommand_positionals(segment.argv, limit=_ROUTE_WORDS))
    return any(words[:size] in _QUIET_ROUTES for size in range(1, len(words) + 1))


def _quiet_segment(segment: ShellSegment) -> bool:
    if any(mark in token for token in segment.tokens for mark in _SHELL_WRITES):
        return False
    if segment.program == "yoke":
        return _quiet_yoke(segment)
    if segment.program == "cd":
        return len(segment.argv) <= 2
    return segment.program == "git" and is_read_only_git_inspection(segment)


def is_quiet_tool_call(tool_name: str, tool_input: Any) -> bool:
    """True when a completed tool call reads or keeps the books, not works."""
    if canonical_tool_name(tool_name or "") in _READ_TOOLS:
        return True
    command = extract_command({"tool_input": tool_input})
    if not command:
        return False
    parsed = parse_shell(command)
    return bool(parsed.segments) and not parsed.unparsed and all(
        _quiet_segment(segment) for segment in parsed.segments
    )


def unpark_after_work(conn: Any, envelope: dict[str, Any]) -> bool:
    """Clear a park only for successful activity beyond reads and bookkeeping."""
    detail = (envelope.get("context") or {}).get("detail") or {}
    tool_input = detail.get("tool_input")
    if isinstance(tool_input, str):
        try:
            tool_input = json.loads(tool_input)
        except (ValueError, TypeError):
            tool_input = {"command": tool_input}
    if is_quiet_tool_call(str(envelope.get("tool_name") or ""), tool_input):
        return False
    return clear_parked_mode(conn, str(envelope["session_id"]))
