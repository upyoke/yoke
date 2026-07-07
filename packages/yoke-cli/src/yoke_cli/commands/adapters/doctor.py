"""``yoke doctor run`` flag adapter.

Covers ``doctor.run.run`` — machine-callable Doctor surface. Exactly
one scope flag (``--quick`` | ``--full`` | ``--only NAMES``) is required;
the explicit-scope rule mirrors the human CLI and is enforced server-side.
"""

from __future__ import annotations

import argparse
from typing import Any, Dict, List

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


__all__ = ["doctor_run", "DOCTOR_RUN_USAGE"]


DOCTOR_RUN_READ_TIMEOUT_S = 300.0
DOCTOR_CHUNK_MAX_CHECKS = 1

DOCTOR_RUN_USAGE = (
    "yoke doctor run (--quick | --full | --only NAMES) [--fix] "
    "[--project NAME] [--db-path PATH] [--session-id S] [--json]"
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
    parser.add_argument("--project", default="yoke",
                        help="Project to run against (default: yoke).")
    parser.add_argument("--db-path", dest="db_path", default=None,
                        help="Optional DB path override.")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, DOCTOR_RUN_USAGE)
    if parsed is None:
        return 2
    payload: Dict[str, Any] = {
        "project": parsed.project,
        "quick": bool(parsed.quick),
        "full": bool(parsed.full),
        "fix": bool(parsed.fix),
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
    final_scope = None
    final_project = payload.get("project") or "yoke"
    last_response: FunctionCallResponse | None = None

    while True:
        chunk_payload = dict(payload)
        chunk_payload["max_checks"] = DOCTOR_CHUNK_MAX_CHECKS
        chunk_payload["skip_source_tree_checks"] = True
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
        final_scope = result.get("scope") or final_scope
        final_project = result.get("project") or final_project
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
            "fail_count": fail_count,
            "warn_count": warn_count,
            "pass_count": pass_count,
        },
        event_ids=event_ids,
        warnings=warnings,
    )
    return emit_response(final_response, json_mode=json_mode)
