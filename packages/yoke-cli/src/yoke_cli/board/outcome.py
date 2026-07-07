"""Board rebuild result type and status constants (client-tier).

Shaped like ``yoke_core.domain.rebuild_board_outcome`` so the shared
human/json formatters read ``status`` / ``board_path`` / ``targets`` /
``exit_code`` identically across both tiers — but with no ``yoke_core`` import,
so formatting a rebuild result never loads engine code.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

# Board rebuild outcome statuses — mirror the source-dev
# ``yoke_core.domain.rebuild_board_outcome`` constants.
REBUILT = "rebuilt"
PRINTED = "printed"
THROTTLED = "throttled"
LOCK_SKIPPED = "lock_skipped"
FAILED = "failed"


@dataclass(frozen=True, eq=False)
class RebuildResult:
    """Result of a CLI-tier board rebuild."""

    status: str
    exit_code: int
    board_path: str = ""
    message: str = ""
    children: tuple["RebuildResult", ...] = field(default_factory=tuple)

    @property
    def changed(self) -> bool:
        if self.children:
            return any(child.changed for child in self.children)
        return self.status == REBUILT

    def __int__(self) -> int:
        return int(self.exit_code)

    def __bool__(self) -> bool:
        return self.exit_code == 0


def rebuilt(path: Path) -> RebuildResult:
    return RebuildResult(REBUILT, 0, str(path), f"Board rebuilt: {path}")


def printed(path: Path) -> RebuildResult:
    return RebuildResult(
        PRINTED, 0, str(path), f"Board rendered without writing: {path}",
    )


def throttled(path: Path, seconds: int) -> RebuildResult:
    return RebuildResult(
        THROTTLED, 0, str(path),
        f"Board rebuild throttled: {path} (last rebuilt < {seconds}s ago)",
    )


def lock_skipped(path: Path) -> RebuildResult:
    return RebuildResult(
        LOCK_SKIPPED, 1, str(path),
        "Board rebuild lock timeout -- another session may be rebuilding. "
        f"Skipped: {path}",
    )


def failed(path: Path, message: str) -> RebuildResult:
    return RebuildResult(FAILED, 1, str(path), message)


__all__ = [
    "FAILED",
    "LOCK_SKIPPED",
    "PRINTED",
    "REBUILT",
    "RebuildResult",
    "THROTTLED",
    "failed",
    "lock_skipped",
    "printed",
    "rebuilt",
    "throttled",
]
