"""Named self-host runtime refusals that never carry credentials."""

from __future__ import annotations

from pathlib import Path

_DEFAULT_RECOVERY = (
    "inspect the captured details and `docker compose logs core db`, "
    "then repair the named cause"
)


class SelfHostRuntimeError(RuntimeError):
    """The bootstrap refused without exposing credentials."""

    def __init__(self, message: str, detail_lines=()) -> None:
        super().__init__(message)
        self.detail_lines = tuple(detail_lines)


def refuse(
    reason: str, directory: Path, recovery: str = _DEFAULT_RECOVERY, detail_lines=()
) -> SelfHostRuntimeError:
    """Name *reason*, its *recovery* and the bundle, keeping details separate."""
    return SelfHostRuntimeError(
        f"{reason}: self-host bootstrap did not complete in {directory}; "
        f"{recovery}, then retry the original self-host command",
        detail_lines,
    )
