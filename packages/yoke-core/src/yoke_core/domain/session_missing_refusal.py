"""Teach how to obtain a registered session when a write requires one.

Unregistered folders deliberately keep hooks local. A missing session there
is expected; a registered project with broken registration needs diagnosis.
The server cannot infer the client folder from its own machine config.
"""

from __future__ import annotations

from yoke_contracts.field_note_text import DENIAL_FOOTER

from typing import Any


#: How a terminal caller reaches a function that requires a session.
TERMINAL_SUPPORTED_PATH = (
    "Run the same command from a Yoke harness session (claude, codex or cursor) "
    "started in the project folder, or run `yoke sessions begin`."
)


def format_session_missing(
    function_id: str,
    *,
    channels: str,
    contested: Any = None,
    harness_family: str = "",
) -> str:
    """Return the refusal for ``function_id``, addressed to its caller."""
    extra = f" contested_anchors={contested}" if contested else ""
    opening = (
        f"mutating function {function_id!r} could not resolve an ambient "
        f"harness session for this process. Consulted: {channels}.{extra} "
    )
    if not harness_family:
        return opening + (
            f"This process is not running under a harness; this write requires "
            f"a session. {TERMINAL_SUPPORTED_PATH}"
        )
    return opening + (
        f"This write requires a registered session. {TERMINAL_SUPPORTED_PATH} "
        "Outside registered projects, hooks deliberately create no session. "
        "If this session started in a registered project, this is a Yoke "
        f"infrastructure gap: registration or process-anchor resolution failed. {DENIAL_FOOTER}"
    )


__all__ = ["TERMINAL_SUPPORTED_PATH", "format_session_missing"]
