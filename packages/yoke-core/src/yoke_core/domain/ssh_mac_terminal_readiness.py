"""Bounded terminal-screen readiness polling for interactive recipes."""

from __future__ import annotations

from collections.abc import Callable, Sequence
import time

from yoke_contracts.designed_wait import announce_designed_wait, poll_every
from yoke_contracts.runtime_ports.ssh_mac_terminal_capture import get_ssh_mac_terminal_capture
from yoke_core.domain.ssh_mac_terminal_recipe_support import (
    capture_recipe_transcript,
)



RunRemote = get_ssh_mac_terminal_capture().RunRemote

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
    announced = False
    while True:
        transcript = read_transcript()
        if all(marker in transcript for marker in expected):
            return True, transcript
        if time.monotonic() >= deadline:
            return False, transcript
        if not announced:
            announced = True
            announce_designed_wait(
                "the remote terminal to show its ready markers",
                max_wait_seconds=timeout_seconds,
                cadence=poll_every(READY_POLL_SECONDS),
            )
        time.sleep(READY_POLL_SECONDS)


__all__ = [
    "DEFAULT_READY_TIMEOUT_SECONDS",
    "wait_for_ready_text",
    "wait_for_ready_text_with_reader",
]
