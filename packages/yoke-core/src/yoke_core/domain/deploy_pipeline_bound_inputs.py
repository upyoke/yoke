"""Prepare authoritative consumer inputs immediately before workflow dispatch."""

from __future__ import annotations
from typing import Any, Callable, Mapping, Optional
from yoke_contracts.api.function_call import TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.deployment_run_bound_sources import (
    BOUND_SOURCES_PREPARE_FUNCTION_ID,
)
from yoke_core.domain.deployment_run_bound_sources import (
    bound_input_values,
    parse_bound_sources,
)
from yoke_core.domain.deploy_pipeline_unknown_outcome import (
    DeploymentOutcomeUnknown,
    UNKNOWN_CODES,
)
from yoke_core.domain.deployment_start_timing import emit_records


def bound_inputs_for_dispatch(
    config: Mapping[str, Any],
    *,
    name: str,
    run_id: str,
    bound_inputs: Optional[Mapping[str, str]],
    member_items: list[str],
    before_dispatch: Optional[Callable[[Mapping[str, str]], tuple[int, str]]] = None,
) -> tuple[dict[str, str], str]:
    """Refresh unused sources, seal consumption, and update the driver's members.

    A source preparation re-bound is not the one ``before_dispatch`` prepared
    during the readiness wait, so it runs again on the prepared commits.
    """
    resolved = dict(bound_inputs or {})
    declared = config.get("input_bindings") or {}
    if not declared:
        return resolved, ""
    response = call_dispatcher(
        function_id=BOUND_SOURCES_PREPARE_FUNCTION_ID,
        target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
        payload={"stage_name": name},
    )
    emit_records((response.result or {}).get("start_timings"))
    prefix = f"stage {name!r} was not dispatched: "
    if not response.success and response.error and response.error.code in UNKNOWN_CODES:
        # Read the existing run owner once. Absence is unknown, never proof
        # that the server stopped or a reason to issue another mutation.
        observed = call_dispatcher(
            function_id="deployment_runs.get",
            target=TargetRef(kind="workflow_run", workflow_run_id=run_id),
            payload={"fields": ["status", "current_stage", "bound_sources"]},
        )
        run = (observed.result or {}).get("run") or {}
        record = parse_bound_sources(run.get("bound_sources"))
        receipt = record.get("preparation_receipt") or {}
        if (
            observed.success
            and run.get("status") == "executing"
            and run.get("current_stage") == name
            and response.request_id
            and receipt.get("request_id") == response.request_id
            and receipt.get("stage_name") == name
        ):
            result = {
                "bound_sources": record,
                "members": receipt.get("members"),
                "rebound": receipt.get("rebound", []),
            }
            response = response.model_copy(
                update={"success": True, "result": result, "error": None}
            )
        else:
            raise DeploymentOutcomeUnknown(
                run_id,
                BOUND_SOURCES_PREPARE_FUNCTION_ID,
                response.request_id,
                response.error.message,
            )
    if not response.success:
        reason = response.error.message if response.error else "request failed"
        return resolved, (
            f"{prefix}{BOUND_SOURCES_PREPARE_FUNCTION_ID} refused: {reason}; ask the control-plane "
            "operator to repair the named authority (for a self-deploy, use the "
            f"candidate's paired source-dev authority), then re-drive {run_id}"
        )
    result = response.result or {}
    record = result.get("bound_sources")
    members = result.get("members")
    if not isinstance(record, dict) or not isinstance(members, list):
        return resolved, (
            f"{prefix}bound_source_preparation_receipt_missing: the serving build "
            "must carry bound source preparation; ask the control-plane operator "
            f"to use the candidate's paired source-dev authority, then re-drive {run_id}"
        )
    resolved = bound_input_values(record)
    missing = sorted(set(declared) - set(resolved))
    if missing or any(not resolved[key] for key in declared):
        return resolved, (
            f"{prefix}bound_source_preparation_receipt_incomplete: run {run_id} "
            f"lacks source commits for {missing or sorted(declared)}; ask the "
            "control-plane operator to repair preparation, then re-drive the run"
        )
    if any(not isinstance(m, dict) or not m.get("public_ref") for m in members):
        return (
            resolved,
            f"{prefix}bound_source_member_receipt_invalid; ask the control-plane operator to repair preparation",
        )
    member_items[:] = [str(m["public_ref"]) for m in members]
    for change in result.get("rebound") or []:
        print(
            f"Bound source re-bound: {change['project']} {change['frozen_sha']} "
            f"-> {change['current_sha']} before {name}; delivery members re-derived"
        )
    if before_dispatch is not None and resolved != dict(bound_inputs or {}):
        rc, diagnostic = before_dispatch(resolved)
        if rc != 0:
            return resolved, f"{prefix}{diagnostic}"
    return resolved, ""
