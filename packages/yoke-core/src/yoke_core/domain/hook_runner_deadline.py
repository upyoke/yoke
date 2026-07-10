"""Total hook deadline helpers for the shared hook runner.

Wheel-shipped home: the ``POST /v1/hooks/evaluate`` route clamps request
deadlines to :func:`resolve_total_timeout_ms`, so the budget resolution
must import on a wheels-only install (no repo tree on ``sys.path``). The
repo-tree hook runner (``runtime.harness.hook_runner``) imports these
helpers from here.

Distinct from :mod:`yoke_harness.hooks.deadline`, the CLIENT-side budget:
that one reads the ``YOKE_HOOK_TOTAL_TIMEOUT_MS`` env var on the relaying
machine, while this server/source-side budget reads the machine-config
keys via :mod:`yoke_core.domain.runtime_settings`.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable

from yoke_core.domain.runtime_settings import get_int


MODULE_TIMEOUT_CONFIG_KEY = "hook_runner_module_timeout_ms"
MODULE_TIMEOUT_DEFAULT_MS = 10000
TOTAL_TIMEOUT_CONFIG_KEY = "hook_runner_total_timeout_ms"
TOTAL_TIMEOUT_DEFAULT_MS = 3000

Clock = Callable[[], float]


def _positive_config_int(key: str, default: int) -> int:
    value = get_int(key, default)
    return value if value > 0 else default


def resolve_module_timeout_ms() -> int:
    """Return the legacy per-module timeout ceiling."""

    return _positive_config_int(MODULE_TIMEOUT_CONFIG_KEY, MODULE_TIMEOUT_DEFAULT_MS)


def resolve_total_timeout_ms() -> int:
    """Return the total harness-wait budget for one hook dispatch."""

    return _positive_config_int(TOTAL_TIMEOUT_CONFIG_KEY, TOTAL_TIMEOUT_DEFAULT_MS)


@dataclass(frozen=True)
class HookDeadline:
    """Monotonic deadline shared across modules, rendering, and telemetry."""

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
        """Return a positive timeout no larger than the remaining budget."""

        remaining = self.remaining_ms()
        if remaining <= 0:
            return 1
        return max(1, min(int(ceiling_ms), remaining))

    def telemetry_allowed(self) -> bool:
        """Whether synchronous main-event telemetry may still be attempted."""

        return self.remaining_ms() > 0


def start_hook_deadline(*, clock: Clock = time.monotonic) -> HookDeadline:
    return HookDeadline(
        budget_ms=resolve_total_timeout_ms(),
        started_at=clock(),
        clock=clock,
    )


__all__ = [
    "HookDeadline",
    "MODULE_TIMEOUT_CONFIG_KEY",
    "MODULE_TIMEOUT_DEFAULT_MS",
    "TOTAL_TIMEOUT_CONFIG_KEY",
    "TOTAL_TIMEOUT_DEFAULT_MS",
    "resolve_module_timeout_ms",
    "resolve_total_timeout_ms",
    "start_hook_deadline",
]
