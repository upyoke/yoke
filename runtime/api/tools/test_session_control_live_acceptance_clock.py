"""Controllable time boundary for Fleet live-acceptance tests."""

from __future__ import annotations

from collections.abc import Callable


class AcceptanceClock:
    def __init__(self, on_sleep: Callable[[], None] | None = None) -> None:
        self.value = 0.0
        self.on_sleep = on_sleep or (lambda: None)

    def monotonic(self) -> float:
        return self.value

    def sleep(self, seconds: float) -> None:
        self.value += max(seconds, 0.001)
        self.on_sleep()


__all__ = ["AcceptanceClock"]
