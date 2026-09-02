"""Explain a mutating call that resolved no harness session.

The same missing session means two different things, and one message for
both taught the wrong recovery to whichever caller it was not written
for.

Inside a harness, a session should have been there: registration or
process-anchor resolution failed, the operator can do nothing about it
from the prompt, and reporting it is the whole recovery.

In a plain terminal there was never going to be one, and the operator
did nothing wrong. Most of what a person runs from a shell declares
itself session-optional and binds the operating actor instead
(:mod:`yoke_core.domain.terminal_reachable_functions`); what is left
requires a session because it takes a work claim, and a claim belongs to
a session. So the recovery is to run the same command from a harness
session — not to file a report about an operation that is behaving as
designed. A live install produced the harness text on a terminal, and
its operator was told to file a field-note about their own first
command.
"""

from __future__ import annotations

from typing import Any


#: How a terminal caller reaches a function that requires a session.
TERMINAL_SUPPORTED_PATH = (
    "Run the same command from a Yoke harness session — start a supported "
    "harness (claude, codex, or cursor) in this project and run it there, "
    "so the session the operation is recorded against exists."
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
            "This process is not running under a harness, and this "
            "operation is one that requires a session — a claim-holding or "
            "session-scoped write, unlike the terminal operations "
            f"onboarding runs. {TERMINAL_SUPPORTED_PATH}"
        )
    return opening + (
        "This is a Yoke infrastructure gap (session registration or "
        "process-anchor resolution failed), not something to work around "
        "— file a field-note if you can, otherwise report it to the "
        "operator. Operator-debug only: an explicit session id "
        "(--session-id) overrides ambient resolution."
    )


__all__ = ["TERMINAL_SUPPORTED_PATH", "format_session_missing"]
