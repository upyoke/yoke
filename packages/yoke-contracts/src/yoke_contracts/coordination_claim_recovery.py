"""Canonical human recovery command for a stranded coordination claim."""

from __future__ import annotations

import shlex


OPERATOR_RELEASE_USAGE = (
    "yoke coordination-claim release --project P --key K --claim-id N "
    "--holder-session-id S --reason R [--json]"
)
OPERATOR_RELEASE_REASON_EXAMPLE = "stale holder confirmed"


def operator_release_command(
    project: str | int,
    key: str,
    *,
    claim_id: int,
    holder_session_id: str,
    reason: str = OPERATOR_RELEASE_REASON_EXAMPLE,
) -> str:
    """Render the runnable human-only recovery command for one claim."""
    return " ".join(
        (
            "yoke coordination-claim release --project",
            shlex.quote(str(project)),
            "--key",
            shlex.quote(str(key)),
            "--claim-id",
            str(int(claim_id)),
            "--holder-session-id",
            shlex.quote(str(holder_session_id)),
            "--reason",
            shlex.quote(str(reason)),
        )
    )


__all__ = [
    "OPERATOR_RELEASE_REASON_EXAMPLE",
    "OPERATOR_RELEASE_USAGE",
    "operator_release_command",
]
