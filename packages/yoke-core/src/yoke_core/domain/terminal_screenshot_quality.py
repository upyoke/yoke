"""Case-local quality checks for terminal screenshot evidence."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path


class TerminalScreenshotRegistry:
    """Detect exact cross-checkpoint screenshot reuse inside one case."""

    def __init__(self) -> None:
        self._checkpoint_by_digest: dict[str, str] = {}

    def duplicate_of(self, checkpoint: str, path: Path) -> str | None:
        digest = sha256(path.read_bytes()).hexdigest()
        previous = self._checkpoint_by_digest.get(digest)
        if previous is None:
            self._checkpoint_by_digest[digest] = checkpoint
        return previous


__all__ = ["TerminalScreenshotRegistry"]
