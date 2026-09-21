"""Shared structural contract for executable Browser QA method cases."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Optional, Sequence


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
#: Shared optional fields every action may carry. Must match
#: ``browser_runtime/src/step-schema.js``.
SHARED_STEP_KEYS = frozenset(
    {
        "action",
        "timeout_ms",
        "source_ac",
        "refined",
        "viewport",
    }
)
ACTION_STEP_KEYS = {
    "navigate": frozenset({"route"}),
    "click": frozenset({"target"}),
    "type": frozenset({"target", "value", "delay"}),
    "fill_form": frozenset({"fields"}),
    "assert": frozenset({"target", "check", "expected", "min_count"}),
    "screenshot": frozenset({"capture", "fullPage"}),
    "wait_for": frozenset({"target"}),
    "delay": frozenset({"duration", "duration_ms"}),
    "scroll": frozenset({"target", "x", "y"}),
    "hover": frozenset({"target"}),
    "select": frozenset({"target", "value"}),
}


@dataclass(frozen=True)
class BrowserMethodContractViolation:
    """One reason a Browser method cannot produce its declared verdict."""

    code: str
    message: str


def _non_empty_text(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def defined_keys_for_action(action: str) -> frozenset[str]:
    """Return the keys *action* honours, including shared optional fields."""
    extra = ACTION_STEP_KEYS.get(action)
    if extra is None:
        return SHARED_STEP_KEYS
    return SHARED_STEP_KEYS | extra


def _unrecognized_step_keys(step: dict[str, Any]) -> list[str]:
    action = step.get("action")
    if action not in ACTION_STEP_KEYS:
        return []
    allowed = defined_keys_for_action(str(action))
    return sorted(key for key in step if key not in allowed)


def _step_key_violation(
    index: int,
    step: dict[str, Any],
) -> Optional[BrowserMethodContractViolation]:
    unknown = _unrecognized_step_keys(step)
    if not unknown:
        return None
    action = step.get("action")
    defined = ", ".join(sorted(defined_keys_for_action(str(action))))
    labelled = ", ".join(repr(key) for key in unknown)
    noun = "key" if len(unknown) == 1 else "keys"
    return BrowserMethodContractViolation(
        "step_key_unrecognized",
        f"Browser {action} step {index} does not honour {noun} "
        f"{labelled}. Defined keys: {defined}",
    )


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
        key_violation = _step_key_violation(index, raw_step)
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
    "defined_keys_for_action",
    "case_viewport",
    "is_browser_assertion",
]
