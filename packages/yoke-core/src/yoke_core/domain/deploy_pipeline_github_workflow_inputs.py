"""Workflow input normalization and durable dispatch-key construction."""

from __future__ import annotations

from typing import Any, Dict


def workflow_inputs(config: Dict[str, Any]) -> Dict[str, str]:
    """Normalize configured workflow inputs to string key/value pairs."""
    raw = config.get("inputs", {})
    if not raw:
        return {}
    if isinstance(raw, dict):
        return {
            str(key): str(value)
            for key, value in raw.items()
            if value is not None
        }
    if isinstance(raw, list):
        result: Dict[str, str] = {}
        for item in raw:
            key, separator, value = str(item).partition("=")
            if separator and key:
                result[key] = value
        return result
    return {}


def resolve_workflow_inputs(
    values: Dict[str, str],
    *,
    head_sha: str,
) -> Dict[str, str]:
    """Resolve supported source-SHA placeholders in workflow inputs."""
    replacements = {
        "{head_sha}": head_sha,
        "$head_sha": head_sha,
        "${head_sha}": head_sha,
    }
    return {
        key: replacements.get(value, value)
        for key, value in values.items()
    }


def config_bool(value: Any) -> bool:
    """Interpret workflow-stage boolean settings consistently."""
    if isinstance(value, str):
        return value.strip().lower() not in {"", "0", "false", "no", "off"}
    return bool(value)


def workflow_dispatch_request_id(
    project: str,
    run_id: str,
    stage_name: str,
    *,
    retrigger_scope: str = "",
) -> str:
    """Return the idempotency key for one logical workflow dispatch.

    The base key keeps ordinary resume/retry calls attached to the same
    dispatch. Intentional retriggers add a scope: ``fresh`` gets a per-call
    nonce, while stale GitHub runs use their predecessor run id so a lost
    response can safely be retried without creating another run.
    """
    base = f"deploy:{project}:{run_id}:{stage_name}"
    if not retrigger_scope:
        return base
    return f"{base}:{retrigger_scope}"


__all__ = [
    "config_bool",
    "resolve_workflow_inputs",
    "workflow_dispatch_request_id",
    "workflow_inputs",
]
