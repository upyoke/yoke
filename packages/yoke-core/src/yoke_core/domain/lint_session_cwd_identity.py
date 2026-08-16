"""Identity-resolution denial for session-cwd write guards.

An unidentified caller is not a foreign lane holder. Occupancy compares
the caller's session id to the live claim on the target lane; an empty
id makes the caller's own claim look like somebody else's. This module
is the denial that fires instead, naming the infrastructure gap and the
identify-yourself recovery — never a cue to take the claim.
"""

from __future__ import annotations

from yoke_core.domain.session_ambient_identity import AMBIENT_RESOLUTION_FAILED

FAILURE_CLASS = "identity_resolution"


def build_denial_message() -> str:
    """Refuse the call because the caller could not be identified."""
    return "\n".join(
        [
            "Refusing this tool call because ambient session identity "
            "could not be resolved.",
            "",
            "This is an identity-resolution failure, not a foreign "
            "lane holder. Identify yourself through the canonical "
            "ambient chain (env, process-anchor registry, "
            "cursor-session-map); do not infer identity from the board "
            "or export session env vars to self-bootstrap.",
            "",
            AMBIENT_RESOLUTION_FAILED,
        ]
    )


__all__ = ["FAILURE_CLASS", "build_denial_message"]
