"""HTTPS ``yoke doctor run`` chunked relay + local compose orchestration.

Each relayed batch carries one check, so its response is also this
transport's progress tick: the verdicts it returns are rendered as
per-check lines the moment they arrive, which is what lets a watcher
follow a relayed run instead of waiting out the whole roster in silence.
"""

from __future__ import annotations

from typing import Any, Dict
import time
from yoke_contracts.doctor_budget import CHUNK_BUDGET_S, RUN_BUDGET_S

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
from yoke_cli.commands.adapters.doctor_https_errors import (
    control_plane_failure_row,
    partial_error,
    run_budget_exhausted,
)
from yoke_cli.commands.adapters.doctor_output import (
    emit_doctor_response,
    emit_relayed_progress,
)


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
        partition_only_slugs,
        recount,
        requested_local_machine_slugs,
        run_local_project_checks,
        run_local_runtime_checks,
        run_local_source_checks,
    )

    # Project-local --only slugs live in the caller checkout; strip them from
    # the relayed payload so undeployed checks are not rejected server-side.
    relay_payload, local_project_slugs = prepare_https_only_payload(payload)
    local_machine, _ = requested_local_machine_slugs(payload)
    if relay_payload.get("only") and local_machine:
        _, relay_only = partition_only_slugs(relay_payload["only"], local_machine)
        if relay_only:
            relay_payload["only"] = relay_only
        else:
            relay_payload.pop("only")
    if not https_relay_needed(relay_payload):
        project = str(payload.get("project") or "")
        local_result = local_project_only_result(
            project=project,
            slugs=local_project_slugs,
            fix=bool(payload.get("fix")),
            runtime=str(payload.get("runtime") or DESTINATION_LOCAL),
        )
        if local_machine:
            rows = merge_relayed_with_local(
                local_result["results"],
                run_local_runtime_checks(
                    project=project,
                    quick=False,
                    fix=bool(payload.get("fix")),
                    slugs=local_machine,
                ),
            )
            local_result.update(results=rows, **recount(rows))
            local_result["composed"] = (
                "local_project_checks+local_runtime"
                if local_project_slugs
                else "local_runtime"
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
    # A rejected request has no execution to compose into a partial report.
    if (
        not response.success
        and response.error
        and response.error.code
        in {"invalid_check", "scope_required", "payload_invalid"}
        and not (response.result or {}).get("completed_control_plane_batches")
    ):
        return emit_doctor_response(
            response, json_mode=json_mode, report_file=report_file
        )
    relay_failed = not response.success

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
        local_runtime = sorted(
            set(false_na_local_runtime_slugs(results)) | set(local_machine)
        )
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
        results.append(control_plane_failure_row(response))
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
        error=partial_error(response) if relay_failed else None,
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


def _scope_label(payload: Dict[str, Any]) -> str:
    if payload.get("only"):
        return "only"
    return "quick" if payload.get("quick") else "full"


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
    final_project = payload.get("project") or ""
    last_response: FunctionCallResponse | None = None
    completed_batches = 0
    deadline = time.monotonic() + RUN_BUDGET_S

    while True:
        chunk_payload = dict(payload)
        chunk_payload["max_checks"] = chunk_max_checks
        if payload.get("quick") and not any(
            payload.get(key) for key in ("full", "only", "fix", "db_path")
        ):
            chunk_payload["project_safe_quick"] = True
        if cursor:
            chunk_payload["cursor_after"] = cursor
        remaining = deadline - time.monotonic()
        response = (
            run_budget_exhausted()
            if remaining <= 0
            else call_dispatcher(
                function_id="doctor.run.run",
                target=target,
                payload=chunk_payload,
                actor=actor,
                timeout_s=min(timeout_s, CHUNK_BUDGET_S, remaining),
            )
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
