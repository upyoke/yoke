"""The wall-clock budget one ``yoke hook evaluate`` process may spend.

``YOKE_HOOK_TOTAL_TIMEOUT_MS`` sets it; the budget is capped below the
shortest hook timeout any supported harness enforces, so no setting and no
cold start can make a harness kill the hook before Yoke answers. The client
spends it on reaching, starting and hearing from the resident evaluator, and
an in-process fallback gets only what is left.
"""

from __future__ import annotations

from typing import Mapping

from yoke_contracts.harness_machine_hooks import HARNESS_MACHINE_HOOKS


TOTAL_TIMEOUT_ENV = "YOKE_HOOK_TOTAL_TIMEOUT_MS"
TOTAL_TIMEOUT_DEFAULT_MS = 10000
# Room under the harness timeout for the hook process's own start and exit.
HARNESS_TIMEOUT_HEADROOM_MS = 5000


def harness_budget_ceiling_ms() -> int:
    """The largest budget that still ends before every harness's hook timeout."""
    shortest = min(
        spec.hook_timeout_seconds for spec in HARNESS_MACHINE_HOOKS.values()
    )
    return shortest * 1000 - HARNESS_TIMEOUT_HEADROOM_MS


def hook_budget_ms(environment: Mapping[str, str]) -> int:
    """The configured budget, or the default, never above the harness ceiling."""
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
