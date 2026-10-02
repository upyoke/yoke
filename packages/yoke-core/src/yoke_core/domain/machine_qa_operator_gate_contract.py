"""Closed declarative contract for Machine QA operator gates."""

from __future__ import annotations

from collections.abc import Callable, Mapping
import re
from typing import Any
from urllib.parse import urlsplit


def validate_browser_approval_steps(raw: object) -> dict[str, Any]:
    """Validate Yoke approval details supplied by the case's step settings."""
    lists = {"origins", "paths", "rejected_statuses", "denial_text"}
    texts = {
        "url_label",
        "code_label",
        "code_pattern",
        "query_parameter",
        "approval_target",
    }
    if not isinstance(raw, Mapping) or set(raw) != lists | texts:
        raise ValueError(
            "browser_approval step settings must contain every protocol field"
        )
    for key in lists:
        values = raw[key]
        if (
            not isinstance(values, list)
            or not 1 <= len(values) <= 16
            or any(
                not isinstance(value, str) or not value or len(value) > 2048
                for value in values
            )
        ):
            raise ValueError(
                "browser_approval lists must contain bounded nonempty strings"
            )
    for key in texts:
        if not isinstance(raw[key], str) or not raw[key] or len(raw[key]) > 256:
            raise ValueError("browser_approval text must be bounded and nonempty")
    for origin in raw["origins"]:
        parsed = urlsplit(origin)
        if (
            parsed.scheme != "https"
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("browser_approval origins must be literal HTTPS origins")
    for path in raw["paths"]:
        parsed = urlsplit(path)
        if (
            not path.startswith("/")
            or parsed.netloc
            or parsed.scheme
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("browser_approval paths must be literal application paths")
    try:
        re.compile(raw["code_pattern"])
    except re.error:
        raise ValueError(
            "browser_approval code_pattern must be a valid regular expression"
        ) from None
    if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_-]{0,63}", raw["query_parameter"]) is None:
        raise ValueError(
            "browser_approval query_parameter must be a literal parameter name"
        )
    return {key: list(raw[key]) if key in lists else raw[key] for key in sorted(raw)}


def normalize_operator_gate(
    action: Mapping[str, Any],
    normalized_action: dict[str, Any],
    *,
    strings: Callable[..., list[str]],
) -> None:
    """Validate and append the one registered operator gate in place."""
    step = str(normalized_action["step"])
    operator_gate = action.get("operator_gate")
    if operator_gate is not None:
        if operator_gate != "machine_browser_approval":
            raise ValueError("action operator_gate is not registered")
        if normalized_action["keys"] != ["Enter"]:
            raise ValueError("machine_browser_approval must immediately send Enter")
        if "wait_seconds" in normalized_action:
            raise ValueError("operator actions must use a typed gate, not wait_seconds")
        completion_text = strings(
            action.get("completion_text"),
            field="action completion_text",
        )
        gate_timeout = action.get("gate_timeout_seconds")
        if (
            isinstance(gate_timeout, bool)
            or not isinstance(gate_timeout, (int, float))
            or not 1 <= float(gate_timeout) <= 600
        ):
            raise ValueError("action gate_timeout_seconds must be numeric from 1..600")
        normalized_action.update(
            {
                "operator_gate": operator_gate,
                "completion_text": completion_text,
                "gate_timeout_seconds": float(gate_timeout),
            }
        )
        if "browser_approval" in action:
            normalized_action["browser_approval"] = validate_browser_approval_steps(
                action["browser_approval"]
            )
    elif "operator" in step.casefold() and "wait_seconds" in normalized_action:
        raise ValueError("operator actions must use a typed gate, not wait_seconds")
    elif (
        "completion_text" in action
        or "gate_timeout_seconds" in action
        or "browser_approval" in action
    ):
        raise ValueError(
            "completion_text and gate_timeout_seconds require operator_gate"
        )


__all__ = ["normalize_operator_gate", "validate_browser_approval_steps"]
