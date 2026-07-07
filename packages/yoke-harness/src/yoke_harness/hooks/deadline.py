"""Client-side hook deadline helpers."""

from __future__ import annotations

import os
import time
from dataclasses import dataclass
from typing import Callable


TOTAL_TIMEOUT_DEFAULT_MS = 3000
TOTAL_TIMEOUT_ENV = "YOKE_HOOK_TOTAL_TIMEOUT_MS"

Clock = Callable[[], float]


def resolve_total_timeout_ms() -> int:
    """Return the product hook wait budget in milliseconds."""
    raw = os.environ.get(TOTAL_TIMEOUT_ENV, "").strip()
    if raw:
        try:
            value = int(raw)
        except ValueError:
            value = TOTAL_TIMEOUT_DEFAULT_MS
        if value > 0:
            return value
    return TOTAL_TIMEOUT_DEFAULT_MS


@dataclass(frozen=True)
class HookDeadline:
    """Monotonic deadline shared by local evaluation and the HTTPS relay."""

    budget_ms: int
    started_at: float
    clock: Clock = time.monotonic

    def elapsed_ms(self) -> int:
        return max(0, int((self.clock() - self.started_at) * 1000))

    def remaining_ms(self) -> int:
        return max(0, int(self.budget_ms - self.elapsed_ms()))

    def expired(self) -> bool:
        return self.remaining_ms() <= 0

    def child_timeout_ms(self, ceiling_ms: int) -> int:
        remaining = self.remaining_ms()
        if remaining <= 0:
            return 1
        return max(1, min(int(ceiling_ms), remaining))


def start_hook_deadline(*, clock: Clock = time.monotonic) -> HookDeadline:
    return HookDeadline(
        budget_ms=resolve_total_timeout_ms(),
        started_at=clock(),
        clock=clock,
    )


__all__ = [
    "HookDeadline",
    "TOTAL_TIMEOUT_DEFAULT_MS",
    "TOTAL_TIMEOUT_ENV",
    "resolve_total_timeout_ms",
    "start_hook_deadline",
]
