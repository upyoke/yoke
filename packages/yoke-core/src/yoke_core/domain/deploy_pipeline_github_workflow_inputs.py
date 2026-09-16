"""Workflow input normalization and durable dispatch-key construction."""

from __future__ import annotations

import uuid
from typing import Any, Dict, Mapping

#: Built-in placeholders every stage may already use. A declared external
#: input binding (see :mod:`deploy_pipeline_github_workflow_bindings`) that
#: reuses one of these names would silently overwrite the run's own
#: identity, so binding declaration refuses them by name.
RESERVED_INPUT_PLACEHOLDERS = frozenset(
    {"head_sha", "run_id", "target_environment", "preview_slug"}
)

#: Every spelling of the placeholder a stage input uses to receive the
#: run's frozen candidate. A stage that dispatches a deploy without one of
#: these hands the workflow no revision at all, so the workflow deploys
#: whatever its own trigger resolves — which is not this run's candidate.
HEAD_SHA_PLACEHOLDERS = frozenset({"{head_sha}", "$head_sha", "${head_sha}"})

#: The canonical spelling of the placeholder a release-preview stage binds
#: its deploy workflow's preview-name input to, and every spelling accepted.
#: A stage that passes none of these leaves the workflow to name the preview
#: itself, which is how the deployed host and the probed host came apart.
PREVIEW_SLUG_PLACEHOLDER = "{preview_slug}"
PREVIEW_SLUG_PLACEHOLDERS = frozenset(
    {PREVIEW_SLUG_PLACEHOLDER, "$preview_slug", "${preview_slug}"}
)


def carries_head_sha(values: Mapping[str, str]) -> bool:
    """Whether any configured input passes the run's frozen candidate."""
    return any(value in HEAD_SHA_PLACEHOLDERS for value in values.values())


def carries_preview_slug(values: Mapping[str, str]) -> bool:
    """Whether any configured input passes this run's preview name."""
    return any(value in PREVIEW_SLUG_PLACEHOLDERS for value in values.values())


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
    run_id: str = "",
    target_environment: str = "",
    preview_slug: str = "",
    bound: Mapping[str, str] = {},  # noqa: B006 - read-only, never mutated
) -> Dict[str, str]:
    """Resolve supported deployment-run placeholders in workflow inputs.

    ``target_environment`` is the registered name of the environment the run
    deploys to, resolved from the flow's typed environment reference. A
    dispatched workflow that hands an environment coordinate back to a Yoke
    surface must receive that name, never a workflow's own display label.
    ``preview_slug`` is the recorded name of this run's release preview, for
    a stage that deploys one; the workflow publishes it verbatim, so the host
    Yoke probes and the host the workflow stood up are the same string.
    ``bound`` carries a stage's declared external input bindings (see
    :mod:`deploy_pipeline_github_workflow_bindings`), each usable the same
    way as the three built-in placeholders below. A binding sharing a
    reserved name is dropped rather than allowed to overwrite the run's own
    identity — ``resolve_declared_input_bindings`` already refuses to
    declare one, so this is a defensive backstop, not the primary guard.
    """
    bound = {
        key: value for key, value in bound.items()
        if key not in RESERVED_INPUT_PLACEHOLDERS
    }
    replacements = {
        "{head_sha}": head_sha,
        "$head_sha": head_sha,
        "${head_sha}": head_sha,
        "{run_id}": run_id,
        "$run_id": run_id,
        "${run_id}": run_id,
        "{target_environment}": target_environment,
        "$target_environment": target_environment,
        "${target_environment}": target_environment,
        "{preview_slug}": preview_slug,
        "$preview_slug": preview_slug,
        "${preview_slug}": preview_slug,
    }
    for key, value in bound.items():
        replacements[f"{{{key}}}"] = value
        replacements[f"${key}"] = value
        replacements[f"${{{key}}}"] = value
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


def fresh_retrigger_scope() -> str:
    """The scope one explicit ``--fresh`` retrigger dispatches under.

    One ``--fresh`` invocation is one intentional retrigger, so the scope
    stays stable for every transport retry inside that invocation while a
    later ``--fresh`` gets a genuinely new dispatch. A release preview needs
    no exemption: its name comes from the deployment run rather than from
    the dispatch, so a new scope redeploys the *same* preview — safe
    precisely because the candidate is frozen and a second dispatch under
    one run can only ever carry the same commit.
    """
    return f"fresh:{uuid.uuid4().hex}"


__all__ = [
    "PREVIEW_SLUG_PLACEHOLDER",
    "PREVIEW_SLUG_PLACEHOLDERS",
    "carries_head_sha",
    "carries_preview_slug",
    "config_bool",
    "fresh_retrigger_scope",
    "resolve_workflow_inputs",
    "workflow_dispatch_request_id",
    "workflow_inputs",
]
