"""The time one ``yoke hook evaluate`` process may spend.

Two bounds apply. The hook process waits for its answer no longer than the
harness ceiling, which ends before the shortest hook timeout any supported
harness enforces, so no cold start can make a harness kill the hook before
Yoke answers. The evaluation itself runs inside ``YOKE_HOOK_TOTAL_TIMEOUT_MS``
(capped at that ceiling) or what is left of the wait, whichever is shorter.
A cold resident's load is waited out up to the ceiling rather than refused at
the evaluation budget.
"""

from __future__ import annotations

from typing import Mapping

from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS


TOTAL_TIMEOUT_ENV = "YOKE_HOOK_TOTAL_TIMEOUT_MS"
TOTAL_TIMEOUT_DEFAULT_MS = 10000
# Room under the harness timeout for the hook process's own start and exit.
HARNESS_TIMEOUT_HEADROOM_MS = 5000


def harness_budget_ceiling_ms() -> int:
    """How long a hook process may wait: ends before every harness's timeout."""
    shortest = min(
        spec.hook_timeout_seconds for spec in HARNESS_MACHINE_HOOKS.values()
    )
    return shortest * 1000 - HARNESS_TIMEOUT_HEADROOM_MS


def hook_budget_ms(environment: Mapping[str, str]) -> int:
    """The evaluation budget: configured or default, never above the ceiling."""
    raw = environment.get(TOTAL_TIMEOUT_ENV, "").strip()
    try:
        value = int(raw) if raw else TOTAL_TIMEOUT_DEFAULT_MS
    except ValueError:
        value = TOTAL_TIMEOUT_DEFAULT_MS
    if value <= 0:
        value = TOTAL_TIMEOUT_DEFAULT_MS
    return min(value, harness_budget_ceiling_ms())


__all__ = [
    "HARNESS_TIMEOUT_HEADROOM_MS",
    "TOTAL_TIMEOUT_DEFAULT_MS",
    "TOTAL_TIMEOUT_ENV",
    "harness_budget_ceiling_ms",
    "hook_budget_ms",
]
