"""``yoke doctor run`` and ``yoke doctor last-run get`` flag adapters.

``doctor.run.run`` is the machine-callable Doctor surface. Exactly one
scope flag (``--quick`` | ``--full`` | ``--only NAMES``) is required;
the explicit-scope rule mirrors the human CLI and is enforced
server-side. ``doctor.last_run.get`` serves the most recent completed
run recorded in the events journal without re-running any checks.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any, Dict, List

from yoke_contracts.deployment_destination import (
    DESTINATION_HOSTED,
    DESTINATION_LOCAL,
    DESTINATION_SERVER,
)
from yoke_contracts.project_defaults import default_project_for_directory

from yoke_cli.config.onboard_destinations import is_hosted_url

from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    build_actor,
    call_dispatcher,
    dispatch_and_emit,
    emit_response,
    parse_or_usage_error,
)
from yoke_cli.transport.https import resolve_https_connection, TransportError
from yoke_contracts.api.function_call import (
    FunctionCallResponse,
    FunctionError,
    TargetRef,
)


__all__ = [
    "doctor_run", "DOCTOR_RUN_USAGE",
    "doctor_last_run_get", "DOCTOR_LAST_RUN_GET_USAGE",
]


DOCTOR_RUN_READ_TIMEOUT_S = 300.0
DOCTOR_CHUNK_MAX_CHECKS = 1

DOCTOR_RUN_USAGE = (
    "yoke doctor run (--quick | --full | --only NAMES) [--fix] "
    "[--project NAME] [--db-path PATH] [--session-id S] [--json]"
)

DOCTOR_LAST_RUN_GET_USAGE = (
    "yoke doctor last-run get [--project NAME] [--session-id S] [--json]"
)


def doctor_last_run_get(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke doctor last-run get",
        description=DOCTOR_LAST_RUN_GET_USAGE,
    )
    parser.add_argument(
        "--project", default=None,
        help="Serve only a run recorded for this project (slug or id).",
    )
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DOCTOR_LAST_RUN_GET_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {}
    if parsed.project:
        payload["project"] = parsed.project
    return dispatch_and_emit(
        function_id="doctor.last_run.get",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
    )


def doctor_run(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke doctor run", description=DOCTOR_RUN_USAGE,
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument("--quick", action="store_true",
                       help="Quick scope: sampled critical HCs.")
    scope.add_argument("--full", action="store_true",
                       help="Full scope: every registered HC.")
    scope.add_argument("--only", default=None,
                       help="Comma-separated HC slugs (subset).")
    parser.add_argument("--fix", action="store_true",
                        help="Apply auto-fixes where supported.")
    parser.add_argument(
        "--project", default=None,
        help=(
            "Project to run against. Defaults to the project bound to the "
            "checkout you are standing in."
        ),
    )
    parser.add_argument("--db-path", dest="db_path", default=None,
                        help="Optional DB path override.")
    add_session_arg(parser)
    add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DOCTOR_RUN_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "project": parsed.project or default_project_for_directory(Path.cwd()),
        "quick": bool(parsed.quick),
        "full": bool(parsed.full),
        "fix": bool(parsed.fix),
        "runtime": _runtime_for_active_connection(),
    }
    if parsed.only:
        payload["only"] = parsed.only
    if parsed.db_path:
        payload["db_path"] = parsed.db_path
    if _active_transport_is_https():
        return _dispatch_chunked(
            payload=payload,
            session_id=parsed.session_id,
            json_mode=parsed.json_mode,
        )
    return dispatch_and_emit(
        function_id="doctor.run.run",
        target=TargetRef(kind="global"),
        payload=payload,
        session_id=parsed.session_id, json_mode=parsed.json_mode,
        timeout_s=DOCTOR_RUN_READ_TIMEOUT_S,
    )


def _active_transport_is_https() -> bool:
    try:
        return resolve_https_connection() is not None
    except TransportError:
        return False


def _runtime_for_active_connection() -> str:
    """Which deployment destination will execute the checks.

    The client knows this and the control plane does not: an HTTPS relay
    runs the checks wherever the connection points, while a local-Postgres
    connection dispatches them in-process on this machine. Sending it means
    the runner never has to guess whether it can see a source tree.
    """
    try:
        connection = resolve_https_connection()
    except TransportError:
        return DESTINATION_LOCAL
    if connection is None:
        return DESTINATION_LOCAL
    return (
        DESTINATION_HOSTED
        if is_hosted_url(getattr(connection, "api_url", ""))
        else DESTINATION_SERVER
    )


def _dispatch_chunked(
    *,
    payload: Dict[str, Any],
    session_id: str | None,
    json_mode: bool,
) -> int:
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
        chunk_payload["max_checks"] = DOCTOR_CHUNK_MAX_CHECKS
        # A read-only quick run may be authorized with project-read
        # permission alone, in exchange for the small project-safe check
        # set. Anything wider needs the raw control-plane read permission.
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
            timeout_s=DOCTOR_RUN_READ_TIMEOUT_S,
        )
        last_response = response
        event_ids.extend(response.event_ids)
        warnings.extend(response.warnings)
        if not response.success:
            return emit_response(response, json_mode=json_mode)

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
            guard = response.model_copy(
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
            return emit_response(guard, json_mode=json_mode)
        cursor = str(next_cursor)

    assert last_response is not None
    final_response = FunctionCallResponse(
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
    return emit_response(final_response, json_mode=json_mode)
