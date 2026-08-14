"""Canonical human recovery command for a stranded coordination lease."""

from __future__ import annotations

import shlex


OPERATOR_RELEASE_USAGE = (
    "yoke coordination-lease release --project P --key K --reason R"
)
OPERATOR_RELEASE_REASON_EXAMPLE = "stale holder confirmed"


def operator_release_command(
    project: str | int,
    lease_key: str,
    *,
    reason: str = OPERATOR_RELEASE_REASON_EXAMPLE,
) -> str:
    """Render the runnable human-only recovery command for one lease."""
    return " ".join(
        (
            "yoke coordination-lease release --project",
            shlex.quote(str(project)),
            "--key",
            shlex.quote(str(lease_key)),
            "--reason",
            shlex.quote(str(reason)),
        )
    )


__all__ = [
    "OPERATOR_RELEASE_REASON_EXAMPLE",
    "OPERATOR_RELEASE_USAGE",
    "operator_release_command",
]
