"""Shared structural contract for executable Browser QA method cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence

from yoke_contracts.browser_step_schema import (
    ACTION_STEP_KEYS,
    SHARED_STEP_KEYS,
    defined_keys_for_action,
    step_schema_violation,
)


#: The width and height a browser page is opened at when nothing states one.
#: It is a stated default, not an inherited size: every page the substrate
#: opens is sized before anything loads into it, so no run can be measured at
#: whatever width the run before it happened to leave behind. A case that is
#: about another width says so — ``method_config.viewport`` for the case, or
#: ``step.viewport`` for one step of it.
DEFAULT_BROWSER_VIEWPORT = {"width": 1440, "height": 900}

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
#: Re-exported from the declared schema so callers keep one import path.


@dataclass(frozen=True)
class BrowserMethodContractViolation:
    """One reason a Browser method cannot produce its declared verdict."""

    code: str
    message: str


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _as_contract_violation(
    index: int,
    step: dict[str, Any],
) -> Optional[BrowserMethodContractViolation]:
    found = step_schema_violation(index, step)
    if found is None:
        return None
    return BrowserMethodContractViolation(found.code, found.message)


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
            return BrowserMethodContractViolation(
                "step_not_object",
                f"Browser step {index} must be an object",
            )
        action = raw_step.get("action")
        key_violation = _as_contract_violation(index, raw_step)
        if key_violation is not None:
            return key_violation
        if action == "navigate":
            route_declared = _non_empty_text(raw_step.get("route"))
            if not route_declared:
                return BrowserMethodContractViolation(
                    "navigate_route_missing",
                    f"Browser navigate step {index} requires a non-empty "
                    "route. Defined keys: "
                    + ", ".join(sorted(defined_keys_for_action("navigate"))),
                )
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


def browser_cleanup_contract_violation(
    steps: Any,
) -> Optional[BrowserMethodContractViolation]:
    """Validate a short recovery sequence using the ordinary step vocabulary."""
    if not isinstance(steps, list) or not 1 <= len(steps) <= 5:
        return BrowserMethodContractViolation(
            "cleanup_steps_invalid",
            "method_config.cleanup_steps must contain 1 to 5 Browser steps",
        )
    for index, step in enumerate(steps):
        if (
            not isinstance(step, dict)
            or not isinstance(step.get("action"), str)
            or step["action"] not in ACTION_STEP_KEYS
        ):
            return BrowserMethodContractViolation(
                "cleanup_action_invalid",
                f"Browser cleanup step {index} needs a supported action",
            )
        violation = _as_contract_violation(index, step)
        if violation is not None:
            return violation
        if step["action"] == "navigate" and not _non_empty_text(step.get("route")):
            return BrowserMethodContractViolation(
                "cleanup_route_missing",
                f"Browser cleanup navigate step {index} needs a non-empty route",
            )
    return None


def case_viewport(method_config: Any) -> Any:
    """Return the viewport a case is authored at, or its contract violation.

    Returns a ``{"width": int, "height": int}`` mapping, or a
    :class:`BrowserMethodContractViolation` when the case states a viewport it
    cannot be run at. A case that states none is run at
    :data:`DEFAULT_BROWSER_VIEWPORT`.
    """
    declared = (
        method_config.get("viewport") if isinstance(method_config, dict) else None
    )
    if declared is None:
        return dict(DEFAULT_BROWSER_VIEWPORT)
    if not isinstance(declared, dict):
        return BrowserMethodContractViolation(
            "case_viewport_invalid",
            "method_config.viewport must be an object with numeric width "
            f"and height, got {declared!r}",
        )
    size = {}
    for edge in ("width", "height"):
        value = declared.get(edge)
        if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
            return BrowserMethodContractViolation(
                "case_viewport_invalid",
                f"method_config.viewport needs a positive integer {edge}, "
                f"got {value!r}",
            )
        size[edge] = value
    return size


def is_browser_assertion(step: Any) -> bool:
    """Return whether a validated step contributes to an automatic verdict."""
    return isinstance(step, dict) and step.get("action") == "assert"


__all__ = [
    "DEFAULT_BROWSER_VIEWPORT",
    "BROWSER_CHECK_METHOD",
    "BROWSER_INSPECTION_METHOD",
    "ACTION_STEP_KEYS",
    "BROWSER_METHODS",
    "BrowserMethodContractViolation",
    "SHARED_STEP_KEYS",
    "SUPPORTED_ASSERTION_CHECKS",
    "browser_method_contract_violation",
    "browser_cleanup_contract_violation",
    "defined_keys_for_action",
    "case_viewport",
    "is_browser_assertion",
]
