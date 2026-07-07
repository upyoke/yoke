"""Structured outcomes for board rebuild orchestration."""

from __future__ import annotations

import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import TextIO


REBUILT = "rebuilt"
PRINTED = "printed"
THROTTLED = "throttled"
LOCK_SKIPPED = "lock_skipped"
FAILED = "failed"


@dataclass(frozen=True, eq=False)
class RebuildOutcome:
    """Result returned by ``rebuild_board.rebuild`` and ``rebuild_one``."""

    status: str
    exit_code: int
    board_path: str = ""
    message: str = ""
    children: tuple["RebuildOutcome", ...] = field(default_factory=tuple)

    @property
    def changed(self) -> bool:
        if self.children:
            return any(child.changed for child in self.children)
        return self.status == REBUILT

    def __int__(self) -> int:
        return int(self.exit_code)

    def __bool__(self) -> bool:
        return self.exit_code == 0

    def __eq__(self, other: object) -> bool:
        if isinstance(other, int):
            return self.exit_code == other
        if isinstance(other, RebuildOutcome):
            return (
                self.status,
                self.exit_code,
                self.board_path,
                self.children,
            ) == (
                other.status,
                other.exit_code,
                other.board_path,
                other.children,
            )
        return False


def rebuilt(path: Path) -> RebuildOutcome:
    return RebuildOutcome(REBUILT, 0, str(path), f"Board rebuilt: {path}")


def printed(path: Path) -> RebuildOutcome:
    return RebuildOutcome(
        PRINTED, 0, str(path),
        f"Board rendered without writing: {path}",
    )


def throttled(path: Path, seconds: int) -> RebuildOutcome:
    return RebuildOutcome(
        THROTTLED, 0, str(path),
        f"Board rebuild throttled: {path} (last rebuilt < {seconds}s ago)",
    )


def lock_skipped(path: Path) -> RebuildOutcome:
    return RebuildOutcome(
        LOCK_SKIPPED, 1, str(path),
        "Board rebuild lock timeout -- another session may be rebuilding. "
        f"Skipped: {path}",
    )


def failed(path: Path, message: str) -> RebuildOutcome:
    return RebuildOutcome(FAILED, 1, str(path), message)


def emit(outcome: RebuildOutcome, *, out: TextIO = sys.stdout) -> None:
    if outcome.children:
        for child in outcome.children:
            emit(child, out=out)
        return
    if not outcome.message:
        return
    stream = sys.stderr if outcome.status in {FAILED, LOCK_SKIPPED} else out
    print(outcome.message, file=stream)
