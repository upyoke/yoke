"""Build and validate explicit model-selection launch payloads."""

from __future__ import annotations

import argparse
from typing import Any

from yoke_cli.commands._helpers import usage_error
from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    LaunchModelSelectionError,
    validate_launch_model_selection,
)


def _explicit_payload(parsed: argparse.Namespace) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "project": parsed.project,
        "executor_surface": parsed.executor_surface,
        "allow_surface_fallback": parsed.allow_surface_fallback,
    }
    machine_id = getattr(parsed, "machine_id", None)
    if machine_id:
        payload["machine_id"] = machine_id
    model = str(getattr(parsed, "model", None) or "").strip()
    if model:
        payload["model"] = model
    effort = str(getattr(parsed, "reasoning_effort", None) or "").strip().lower()
    if effort:
        payload["reasoning_effort"] = effort
    context = getattr(parsed, "context_window_tokens", None)
    if context is not None:
        payload["context_window_tokens"] = context
    return payload


def selector_payload(parsed: argparse.Namespace) -> dict[str, Any] | None:
    """Send only explicit values after validating the selected surface."""
    try:
        payload = _explicit_payload(parsed)
        validate_launch_model_selection(
            parsed.executor_surface,
            LaunchModelSelection(
                model=payload.get("model"),
                reasoning_effort=payload.get("reasoning_effort"),
                context_window_tokens=payload.get("context_window_tokens"),
            ),
        )
        return payload
    except LaunchModelSelectionError as exc:
        usage_error(f"{exc.code}: {exc}")
        return None


__all__ = ["selector_payload"]
