"""Canonical human recovery command for a stranded coordination claim."""

from __future__ import annotations

import shlex


OPERATOR_RELEASE_USAGE = (
    "yoke coordination-claim release --project P --key K --reason R [--session-id S]"
)
OPERATOR_RELEASE_REASON_EXAMPLE = "stale holder confirmed"


def operator_release_command(
    project: str | int,
    key: str,
    *,
    reason: str = OPERATOR_RELEASE_REASON_EXAMPLE,
) -> str:
    """Render the runnable human-only recovery command for one claim."""
    return " ".join(
        (
            "yoke coordination-claim release --project",
            shlex.quote(str(project)),
            "--key",
            shlex.quote(str(key)),
            "--reason",
            shlex.quote(str(reason)),
        )
    )


__all__ = [
    "OPERATOR_RELEASE_REASON_EXAMPLE",
    "OPERATOR_RELEASE_USAGE",
    "operator_release_command",
]
