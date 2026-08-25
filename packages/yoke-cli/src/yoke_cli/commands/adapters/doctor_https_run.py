"""HTTPS ``yoke doctor run`` chunked relay + local compose orchestration."""

from __future__ import annotations

from typing import Any, Dict

from yoke_contracts.deployment_destination import DESTINATION_LOCAL
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)

from yoke_cli.commands._helpers import (
    build_actor,
    call_dispatcher,
    emit_response,
)


def dispatch_chunked(
    *,
    payload: Dict[str, Any],
    session_id: str | None,
    json_mode: bool,
    chunk_max_checks: int,
    timeout_s: float,
) -> int:
    from yoke_cli.commands.adapters.doctor_https_compose import (
        false_na_local_runtime_slugs,
        false_na_source_slugs,
        https_relay_needed,
        local_project_only_result,
        machine_has_checkout_for,
        merge_relayed_with_local,
        prepare_https_only_payload,
        recount,
        run_local_project_checks,
        run_local_runtime_checks,
        run_local_source_checks,
    )

    # Project-local --only slugs live in the caller checkout; strip them from
    # the relayed payload so undeployed checks are not rejected server-side.
    relay_payload, local_project_slugs = prepare_https_only_payload(payload)
    if not https_relay_needed(relay_payload):
        project = str(payload.get("project") or "")
        return emit_response(
            FunctionCallResponse(
                success=True,
                function="doctor.run.run",
                version="v1",
                request_id="",
                result=local_project_only_result(
                    project=project,
                    slugs=local_project_slugs,
                    fix=bool(payload.get("fix")),
                    runtime=str(
                        payload.get("runtime") or DESTINATION_LOCAL
                    ),
                ),
            ),
            json_mode=json_mode,
        )

    response = collect_chunked(
        payload=relay_payload,
        session_id=session_id,
        chunk_max_checks=chunk_max_checks,
        timeout_s=timeout_s,
    )
    if not response.success:
        return emit_response(response, json_mode=json_mode)

    result = dict(response.result or {})
    results = list(result.get("results") or [])
    project = str(result.get("project") or payload.get("project") or "")
    composed: list[str] = []
    if local_project_slugs:
        results = merge_relayed_with_local(
            results,
            run_local_project_checks(
                project=project,
                slugs=local_project_slugs,
                fix=bool(payload.get("fix")),
            ),
        )
        composed.append("local_project_checks")
    local_runtime = false_na_local_runtime_slugs(results)
    if local_runtime:
        results = merge_relayed_with_local(
            results,
            run_local_runtime_checks(
                project=project,
                quick=bool(payload.get("quick")),
                fix=bool(payload.get("fix")),
                slugs=local_runtime,
            ),
        )
        composed.append("local_runtime")
    if machine_has_checkout_for(project):
        redo = false_na_source_slugs(results)
        if redo:
            results = merge_relayed_with_local(
                results,
                run_local_source_checks(
                    project=project,
                    quick=bool(payload.get("quick")),
                    full=bool(payload.get("full")),
                    fix=bool(payload.get("fix")),
                    only=payload.get("only"),
                    slugs=redo,
                ),
            )
            composed.append("local_source")
    if composed:
        result.update(recount(results))
        result["results"] = results
        result["runtime"] = result.get("runtime") or payload.get("runtime")
        result["composed"] = "+".join(
            [*composed, "relayed_control_plane"]
        )

    return emit_response(
        FunctionCallResponse(
            success=True,
            function=response.function,
            version=response.version,
            request_id=response.request_id,
            result=result,
            event_ids=response.event_ids,
            warnings=response.warnings,
        ),
        json_mode=json_mode,
    )


def collect_chunked(
    *,
    payload: Dict[str, Any],
    session_id: str | None,
    chunk_max_checks: int,
    timeout_s: float,
) -> FunctionCallResponse:
    actor = build_actor(session_id=session_id)
    target = TargetRef(kind="global")
    cursor = None
    results: list[dict[str, Any]] = []
    event_ids: list[str] = []
    warnings = []
    fail_count = 0
    warn_count = 0
    pass_count = 0
    na_count = 0
    final_runtime = payload.get("runtime") or DESTINATION_LOCAL
    final_scope = None
    final_project = payload.get("project") or "yoke"
    last_response: FunctionCallResponse | None = None

    while True:
        chunk_payload = dict(payload)
        chunk_payload["max_checks"] = chunk_max_checks
        if payload.get("quick") and not any(
            payload.get(key) for key in ("full", "only", "fix", "db_path")
        ):
            chunk_payload["project_safe_quick"] = True
        if cursor:
            chunk_payload["cursor_after"] = cursor
        response = call_dispatcher(
            function_id="doctor.run.run",
            target=target,
            payload=chunk_payload,
            actor=actor,
            timeout_s=timeout_s,
        )
        last_response = response
        event_ids.extend(response.event_ids)
        warnings.extend(response.warnings)
        if not response.success:
            return response

        result = response.result or {}
        results.extend(result.get("results") or [])
        fail_count += int(result.get("fail_count") or 0)
        warn_count += int(result.get("warn_count") or 0)
        pass_count += int(result.get("pass_count") or 0)
        na_count += int(result.get("na_count") or 0)
        final_scope = result.get("scope") or final_scope
        final_project = result.get("project") or final_project
        final_runtime = result.get("runtime") or final_runtime
        next_cursor = result.get("cursor")
        if result.get("done", True):
            break
        if not next_cursor or next_cursor == cursor:
            return response.model_copy(
                update={
                    "success": False,
                    "error": FunctionError(
                        code="doctor_cursor_stalled",
                        message=(
                            "doctor chunk response did not advance its cursor"
                        ),
                    ),
                }
            )
        cursor = str(next_cursor)

    assert last_response is not None
    return FunctionCallResponse(
        success=True,
        function=last_response.function,
        version=last_response.version,
        request_id=last_response.request_id,
        result={
            "results": results,
            "scope": final_scope or "quick",
            "project": final_project,
            "runtime": final_runtime,
            "fail_count": fail_count,
            "warn_count": warn_count,
            "pass_count": pass_count,
            "na_count": na_count,
        },
        event_ids=event_ids,
        warnings=warnings,
    )


__all__ = ["collect_chunked", "dispatch_chunked"]
