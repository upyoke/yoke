"""Shared structural contract for executable Browser QA method cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence


BROWSER_CHECK_METHOD = "browser-check"
BROWSER_INSPECTION_METHOD = "browser-inspection"
BROWSER_METHODS = frozenset(
    {
        BROWSER_CHECK_METHOD,
        BROWSER_INSPECTION_METHOD,
    }
)
SUPPORTED_ASSERTION_CHECKS = frozenset(
    {
        "visible",
        "hidden",
        "text_contains",
        "text_equals",
        "count_gte",
        "count_eq",
    }
)
_EXPECTED_VALUE_CHECKS = frozenset(
    {
        "text_contains",
        "text_equals",
        "count_eq",
    }
)


@dataclass(frozen=True)
class BrowserMethodContractViolation:
    """One reason a Browser method cannot produce its declared verdict."""

    code: str
    message: str


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def browser_method_contract_violation(
    method_id: str,
    steps: Sequence[Any],
) -> Optional[BrowserMethodContractViolation]:
    """Return the first verdict/evidence contract violation, if any.

    Browser execution keeps one current page across step calls. A verdict or
    capture is therefore attributable only after a ``navigate`` step declares
    the route being observed.
    """
    if method_id not in BROWSER_METHODS:
        return None

    route_declared = False
    assertion_count = 0
    capture_count = 0
    for index, raw_step in enumerate(steps):
        if not isinstance(raw_step, dict):
            continue
        action = raw_step.get("action")
        if action == "navigate":
            route_declared = _non_empty_text(raw_step.get("route"))
            continue
        if action == "assert":
            if not route_declared:
                return BrowserMethodContractViolation(
                    "assertion_without_declared_route",
                    "Browser assertions require a preceding navigate "
                    "step with a non-empty route",
                )
            target = raw_step.get("target")
            if not _non_empty_text(target):
                return BrowserMethodContractViolation(
                    "assertion_target_missing",
                    f"Browser assertion step {index} requires a non-empty target",
                )
            check = raw_step.get("check")
            if check not in SUPPORTED_ASSERTION_CHECKS:
                allowed = ", ".join(sorted(SUPPORTED_ASSERTION_CHECKS))
                return BrowserMethodContractViolation(
                    "assertion_check_invalid",
                    f"Browser assertion step {index} requires one of: {allowed}",
                )
            if check in _EXPECTED_VALUE_CHECKS and "expected" not in raw_step:
                return BrowserMethodContractViolation(
                    "assertion_expected_missing",
                    f"Browser assertion step {index} with check "
                    f"{check!r} requires expected",
                )
            if check == "count_gte":
                minimum = raw_step.get("min_count")
                if (
                    isinstance(minimum, bool)
                    or not isinstance(minimum, int)
                    or minimum < 0
                ):
                    return BrowserMethodContractViolation(
                        "assertion_min_count_invalid",
                        f"Browser assertion step {index} with check "
                        "'count_gte' requires a non-negative integer "
                        "min_count",
                    )
            assertion_count += 1
            continue
        if action == "screenshot" and raw_step.get("capture") is True:
            if not route_declared:
                return BrowserMethodContractViolation(
                    "capture_without_declared_route",
                    "Browser screenshot capture requires a "
                    "preceding navigate step with a non-empty route",
                )
            capture_count += 1

    if method_id == BROWSER_CHECK_METHOD and assertion_count == 0:
        return BrowserMethodContractViolation(
            "assertion_missing",
            "browser-check requires at least one verdict-bearing assert step",
        )
    if method_id == BROWSER_INSPECTION_METHOD and capture_count == 0:
        return BrowserMethodContractViolation(
            "capture_missing",
            "browser-inspection requires at least one screenshot step with "
            "capture=true for later judgment",
        )
    return None


def is_browser_assertion(step: Any) -> bool:
    """Return whether a validated step contributes to an automatic verdict."""
    return isinstance(step, dict) and step.get("action") == "assert"


__all__ = [
    "BROWSER_CHECK_METHOD",
    "BROWSER_INSPECTION_METHOD",
    "BROWSER_METHODS",
    "BrowserMethodContractViolation",
    "SUPPORTED_ASSERTION_CHECKS",
    "browser_method_contract_violation",
    "is_browser_assertion",
]
