"""Validate case page settings and check observed media evidence."""

import json

from yoke_contracts.browser_qa_contract import (
    BrowserMethodContractViolation,
    browser_cleanup_contract_violation,
    browser_method_contract_violation,
    case_color_scheme,
    case_viewport,
)


def parse_case_config(raw):
    """Malformed serialized configuration stays a named execution refusal."""
    try:
        config = json.loads(raw) if raw else {}
    except (TypeError, json.JSONDecodeError):
        return {}
    return config if isinstance(config, dict) else {}


def case_settings(method_id, method_config, steps):
    """Resolve the case's viewport/scheme and first structural refusal."""
    viewport = case_viewport(method_config)
    scheme = case_color_scheme(method_config)
    violation = browser_method_contract_violation(str(method_id or ""), steps)
    cleanup = method_config.get("cleanup_steps", [])
    if violation is None and "cleanup_steps" in method_config:
        violation = browser_cleanup_contract_violation(cleanup)
    for setting in (viewport, scheme):
        if violation is None and isinstance(setting, BrowserMethodContractViolation):
            violation = setting
    return viewport, scheme, cleanup, violation


def color_scheme_failure(requested, evidence):
    """A declaration needs an actual matching observation, never an echo."""
    if requested is None:
        return ""
    if not isinstance(evidence, dict) or evidence.get("observed") not in (
        "light",
        "dark",
    ):
        return (
            "color_scheme_observation_missing: no page media preference was observed; "
            "repair the browser daemon and rerun the case"
        )
    if evidence.get("requested") != requested or evidence["observed"] != requested:
        return (
            f"color_scheme_mismatch: requested {requested!r}, got {evidence!r}; "
            "reopen the case page with its declared preference and rerun"
        )
    return ""


def record_color_scheme_observation(state, evidence):
    """Retain the actual observation while keeping the case request distinct."""
    state["observed"] = evidence.get("observed") if isinstance(evidence, dict) else None
    return color_scheme_failure(state["requested"], evidence)
