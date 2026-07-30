"""Terminal screenshot evidence must be checkpoint-specific."""

from __future__ import annotations

from pathlib import Path

from yoke_core.domain.terminal_screenshot_quality import (
    TerminalScreenshotRegistry,
)


def test_exact_cross_checkpoint_duplicate_is_rejected(tmp_path: Path) -> None:
    first = tmp_path / "approval.png"
    second = tmp_path / "review.png"
    first.write_bytes(b"same captured frame")
    second.write_bytes(b"same captured frame")
    registry = TerminalScreenshotRegistry()

    assert registry.duplicate_of("browser-approval", first) is None
    assert registry.duplicate_of("review-frame", second) == "browser-approval"


def test_distinct_checkpoint_bytes_are_retained(tmp_path: Path) -> None:
    first = tmp_path / "approval.png"
    second = tmp_path / "review.png"
    first.write_bytes(b"approval frame")
    second.write_bytes(b"review frame")
    registry = TerminalScreenshotRegistry()

    assert registry.duplicate_of("browser-approval", first) is None
    assert registry.duplicate_of("review-frame", second) is None
