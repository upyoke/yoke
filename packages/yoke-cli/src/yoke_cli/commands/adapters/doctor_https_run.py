"""HTTPS ``yoke doctor run`` chunked relay + local compose orchestration.

Each relayed batch carries one check, so its response is also this
transport's progress tick: the verdicts it returns are rendered as
per-check lines the moment they arrive, which is what lets a watcher
follow a relayed run instead of waiting out the whole roster in silence.
"""

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
)
from yoke_cli.commands.adapters.doctor_https_receipt import (
    persist_composed_receipt,
)
from yoke_cli.commands.adapters.doctor_output import (
    emit_doctor_response,
    emit_relayed_progress,
)


_TRANSPORT_FAILURE_CODE = "https_transport_failed"
_PARTIAL_FAILURE_CODE = "doctor_control_plane_partial"


def dispatch_chunked(
    *,
    payload: Dict[str, Any],
    session_id: str | None,
    json_mode: bool,
    chunk_max_checks: int,
    timeout_s: float,
    report_file: str | None = None,
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
        requested_local_machine_slugs,
        run_local_project_checks,
        run_local_runtime_checks,
        run_local_source_checks,
    )

    # Project-local --only slugs live in the caller checkout; strip them from
    # the relayed payload so undeployed checks are not rejected server-side.
    relay_payload, local_project_slugs = prepare_https_only_payload(payload)
    if not https_relay_needed(relay_payload):
        project = str(payload.get("project") or "")
        local_result = local_project_only_result(
            project=project,
            slugs=local_project_slugs,
            fix=bool(payload.get("fix")),
            runtime=str(payload.get("runtime") or DESTINATION_LOCAL),
        )
        persist_composed_receipt(
            local_result,
            session_id=session_id,
            timeout_s=timeout_s,
        )
        return emit_doctor_response(
            FunctionCallResponse(
                success=True,
                function="doctor.run.run",
                version="v1",
                request_id="",
                result=local_result,
            ),
            json_mode=json_mode,
            report_file=report_file,
        )

    response = collect_chunked(
        payload=relay_payload,
        session_id=session_id,
        chunk_max_checks=chunk_max_checks,
        timeout_s=timeout_s,
    )
    relay_failed = _is_transport_failure(response)
    if not response.success and not relay_failed:
        return emit_doctor_response(
            response, json_mode=json_mode, report_file=report_file
        )

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
    if relay_failed:
        local_runtime, local_source = requested_local_machine_slugs(payload)
    else:
        local_runtime = false_na_local_runtime_slugs(results)
        local_source = false_na_source_slugs(results)
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
        if local_source:
            results = merge_relayed_with_local(
                results,
                run_local_source_checks(
                    project=project,
                    quick=bool(payload.get("quick")),
                    full=bool(payload.get("full")),
                    fix=bool(payload.get("fix")),
                    only=payload.get("only"),
                    slugs=local_source,
                ),
            )
            composed.append("local_source")
    if relay_failed:
        results.append(_control_plane_failure_row(response))
        result["partial"] = True
        result["control_plane_error"] = (
            response.error.model_dump(mode="json") if response.error else {}
        )
        composed.append("relayed_control_plane_failed")
    if composed:
        result.update(recount(results))
        result["results"] = results
        result["scope"] = result.get("scope") or _scope_label(payload)
        result["project"] = project
        result["runtime"] = result.get("runtime") or payload.get("runtime")
        if not relay_failed:
            composed.append("relayed_control_plane")
        result["composed"] = "+".join(composed)

    final = FunctionCallResponse(
        success=not relay_failed,
        function=response.function,
        version=response.version,
        request_id=response.request_id,
        result=result,
        error=_partial_error(response) if relay_failed else None,
        event_ids=response.event_ids,
        warnings=response.warnings,
    )
    if not relay_failed:
        persist_composed_receipt(
            result,
            session_id=session_id,
            timeout_s=timeout_s,
        )
    return emit_doctor_response(
        final,
        json_mode=json_mode,
        report_file=report_file,
    )


def _is_transport_failure(response: FunctionCallResponse) -> bool:
    return bool(
        not response.success
        and response.error
        and response.error.code == _TRANSPORT_FAILURE_CODE
    )


def _scope_label(payload: Dict[str, Any]) -> str:
    if payload.get("only"):
        return "only"
    return "quick" if payload.get("quick") else "full"


def _control_plane_failure_row(
    response: FunctionCallResponse,
) -> Dict[str, str]:
    error = response.error
    code = error.code if error else _TRANSPORT_FAILURE_CODE
    message = error.message if error else "the relay returned no diagnosis"
    return {
        "hc": "HC-doctor-control-plane-batch",
        "name": "Relayed control-plane Doctor batch",
        "severity": "FAIL",
        "detail": (
            f"{code}: {message}. Machine-local checks and --fix actions "
            "still ran; retry the same command after ingress or control-plane "
            "health recovers."
        ),
    }


def _partial_error(response: FunctionCallResponse) -> FunctionError:
    original = response.error
    code = original.code if original else _TRANSPORT_FAILURE_CODE
    message = original.message if original else "relay failed without detail"
    return FunctionError(
        code=_PARTIAL_FAILURE_CODE,
        message=(
            f"bounded control-plane Doctor batch failed ({code}); the attached "
            f"report is partial and machine-local checks completed: {message}"
        ),
        recovery_hint=(
            "Retry the same `yoke doctor run` command after ingress or "
            "control-plane health recovers; the report remains failing until "
            "every relayed batch completes."
        ),
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
    completed_batches = 0

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
            return response.model_copy(
                update={
                    "result": {
                        "results": results,
                        "scope": final_scope or _scope_label(payload),
                        "project": final_project,
                        "runtime": final_runtime,
                        "fail_count": fail_count,
                        "warn_count": warn_count,
                        "pass_count": pass_count,
                        "na_count": na_count,
                        "done": False,
                        "cursor": cursor,
                        "completed_control_plane_batches": completed_batches,
                    },
                    "event_ids": event_ids,
                    "warnings": warnings,
                }
            )

        result = response.result or {}
        batch_rows = result.get("results") or []
        emit_relayed_progress(batch_rows)
        results.extend(batch_rows)
        fail_count += int(result.get("fail_count") or 0)
        warn_count += int(result.get("warn_count") or 0)
        pass_count += int(result.get("pass_count") or 0)
        na_count += int(result.get("na_count") or 0)
        final_scope = result.get("scope") or final_scope
        final_project = result.get("project") or final_project
        final_runtime = result.get("runtime") or final_runtime
        completed_batches += 1
        next_cursor = result.get("cursor")
        if result.get("done", True):
            break
        if not next_cursor or next_cursor == cursor:
            return response.model_copy(
                update={
                    "success": False,
                    "error": FunctionError(
                        code="doctor_cursor_stalled",
                        message=("doctor chunk response did not advance its cursor"),
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
