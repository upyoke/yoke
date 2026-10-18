"""Shared payload builders for the lint_long_command_polling pytest suites.

Every builder carries the client capture fact
(:data:`yoke_contracts.hook_runner.client_facts.CAPTURE_FILES_KEY`): the
client's scratch roots plus the observed state of each capture file a
test names. The polling policy reads only that fact, never the evaluating
machine's filesystem.
"""

from __future__ import annotations

from typing import Mapping, Sequence

from yoke_contracts.hook_runner.client_facts import CAPTURE_FILES_KEY, client_fact

#: Scratch roots a typical macOS client reports.
CAPTURE_ROOTS: tuple[str, ...] = ("/tmp", "/private/tmp")

#: Client-observed capture states.
RUNNING = {"completed": False, "age_seconds": 3.0}
FINISHED = {"completed": True, "age_seconds": 3.0}
STALE = {"completed": False, "age_seconds": 600.0}


def capture_fact(
    files: Mapping[str, Mapping] | None = None,
    *,
    roots: Sequence[str] = CAPTURE_ROOTS,
) -> dict:
    """Return the payload entry for the client capture fact."""
    return client_fact(
        CAPTURE_FILES_KEY,
        {"roots": list(roots), "files": {k: dict(v) for k, v in (files or {}).items()}},
    )


def _bash_payload(
    command: str,
    *,
    description: str = "",
    session_id: str = "sess-test",
    turn_id: str = "turn-1",
    tool_use_id: str = "tu-1",
    captures: Mapping[str, Mapping] | None = None,
    roots: Sequence[str] = CAPTURE_ROOTS,
) -> dict:
    return {
        "tool_name": "Bash",
        "tool_input": {"command": command, "description": description},
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "turn_id": turn_id,
        **capture_fact(captures, roots=roots),
    }


def _non_bash_payload(
    tool_name: str,
    *,
    session_id: str = "sess-test",
    turn_id: str = "turn-1",
    tool_use_id: str = "tu-1",
    tool_input: dict | None = None,
    roots: Sequence[str] = CAPTURE_ROOTS,
) -> dict:
    return {
        "tool_name": tool_name,
        "tool_input": tool_input or {"delaySeconds": 120, "reason": "checking build"},
        "session_id": session_id,
        "tool_use_id": tool_use_id,
        "turn_id": turn_id,
        **capture_fact(roots=roots),
    }
