"""``yoke hook status-line`` — Claude's status line, and what it attests.

Claude Code runs the configured status line command once per turn, hands
it the session's JSON on stdin, and prints its first stdout line under the
composer. That JSON is the only machine-readable surface on which Claude
states the context window it is actually serving, so Yoke configures this
command in the settings it renders: the window it reads becomes the
session's served ``context_window_tokens``, and the line it prints is what
the operator gets in exchange for the slot.

Client-local and tool-shaped by nature — it reads a harness artifact on
this machine and writes machine-local state, with no control-plane call to
dispatch and therefore no function id.
"""

from __future__ import annotations

import sys
from typing import Callable, Dict, List, Tuple

from yoke_contracts.field_note_text import FOOTER as _FIELD_NOTE_FOOTER


CLAUDE_STATUS_LINE_USAGE = (
    "Read Claude's status line JSON on stdin: record the served context "
    "window it states, and print the session's status line."
)


def claude_status_line(args: List[str]) -> int:
    """Record the served context window and print Claude's status line."""
    if any(arg in {"-h", "--help"} for arg in args):
        sys.stdout.write(
            f"yoke hook status-line\n\n{CLAUDE_STATUS_LINE_USAGE}\n\n"
            "Configured by Yoke as the Claude `statusLine` command; not a\n"
            "command to run by hand. Claude allows one status line per\n"
            "session, so an operator who wants their own sets `statusLine`\n"
            "in .claude/settings.local.json, which overrides the project\n"
            "setting — and gives up the served context window attestation\n"
            "with it, since this is the only surface that states it.\n"
            f"\n{_FIELD_NOTE_FOOTER}\n"
        )
        return 0
    try:
        from yoke_harness.claude_status_line import main as status_line_main
    except ImportError:
        # A status line is a display surface: a machine whose harness
        # package is missing shows no line rather than an error where the
        # operator's context percentage belongs.
        return 0
    return status_line_main(args)


TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], Callable[[List[str]], int]] = {
    ("hook", "status-line"): claude_status_line,
}
TOOL_SHAPED_USAGE = {
    "yoke hook status-line": CLAUDE_STATUS_LINE_USAGE,
}


__all__ = [
    "CLAUDE_STATUS_LINE_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "claude_status_line",
]
