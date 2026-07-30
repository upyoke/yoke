"""Bounded terminal-screen readiness polling for interactive recipes."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import time

from yoke_core.domain.ssh_mac_terminal_capture import RunRemote
from yoke_core.domain.ssh_mac_terminal_recipe_support import (
    capture_recipe_transcript,
)


DEFAULT_READY_TIMEOUT_SECONDS = 120.0
READY_POLL_SECONDS = 1.0


def wait_for_ready_text(
    run: RunRemote,
    *,
    backend: str,
    session: str,
    expected: Sequence[str],
    timeout_seconds: float,
) -> tuple[bool, str]:
    """Wait until one terminal frame contains every required source marker."""
    return wait_for_ready_text_with_reader(
        read_transcript=lambda: capture_recipe_transcript(
            run,
            backend=backend,
            session=session,
        ),
        expected=expected,
        timeout_seconds=timeout_seconds,
    )


def wait_for_ready_text_with_reader(
    *,
    read_transcript: Callable[[], str],
    expected: Sequence[str],
    timeout_seconds: float,
) -> tuple[bool, str]:
    """Wait until one terminal reader contains every required source marker."""
    deadline = time.monotonic() + timeout_seconds
    transcript = ""
    while True:
        transcript = read_transcript()
        if all(marker in transcript for marker in expected):
            return True, transcript
        if time.monotonic() >= deadline:
            return False, transcript
        time.sleep(READY_POLL_SECONDS)


__all__ = [
    "DEFAULT_READY_TIMEOUT_SECONDS",
    "wait_for_ready_text",
    "wait_for_ready_text_with_reader",
]
