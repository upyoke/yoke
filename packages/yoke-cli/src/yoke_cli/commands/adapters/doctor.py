"""``yoke doctor run`` and ``yoke doctor last-run get`` flag adapters.

``yoke doctor run`` is the Doctor surface for every transport and the
command ``yoke watch doctor`` wraps. Exactly one scope flag (``--quick``
| ``--full`` | ``--only NAMES``) is required; the explicit-scope rule
mirrors the engine entrypoint and is enforced server-side.

Both transports stream the same per-check progress lines while they
work. A relayed run learns each verdict as its bounded batch returns and
renders the line from that row; a local-Postgres run dispatches in this
same process, so it installs the sink and the handler's own check loop
writes the lines directly. ``doctor.last_run.get`` serves the most
recent completed run recorded in ``doctor_runs`` without re-running any
checks.
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
    dispatch_and_emit,
    ensure_handlers_loaded,
    parse_or_usage_error,
)
from yoke_cli.commands.adapters.doctor_output import (
    emit_doctor_response,
    stream_progress_to_stderr,
)
from yoke_cli.transport.dispatcher import call_dispatcher
from yoke_cli.transport.https import resolve_https_connection, TransportError
from yoke_contracts.api.function_call import TargetRef


__all__ = [
    "doctor_run",
    "DOCTOR_RUN_USAGE",
    "doctor_last_run_get",
    "DOCTOR_LAST_RUN_GET_USAGE",
]


DOCTOR_RUN_READ_TIMEOUT_S = 300.0
DOCTOR_CHUNK_MAX_CHECKS = 1

DOCTOR_RUN_USAGE = (
    "yoke doctor run (--quick | --full | --only NAMES) [--fix] "
    "[--project NAME] [--file PATH] [--db-path PATH] [--session-id S] [--json]"
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
        "--project",
        default=None,
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
        session_id=parsed.session_id,
        json_mode=parsed.json_mode,
    )


def doctor_run(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke doctor run",
        description=DOCTOR_RUN_USAGE,
    )
    scope = parser.add_mutually_exclusive_group(required=True)
    scope.add_argument(
        "--quick", action="store_true", help="Quick scope: sampled critical HCs."
    )
    scope.add_argument(
        "--full", action="store_true", help="Full scope: every registered HC."
    )
    scope.add_argument(
        "--only", default=None, help="Comma-separated HC slugs (subset)."
    )
    parser.add_argument(
        "--fix", action="store_true", help="Apply auto-fixes where supported."
    )
    parser.add_argument(
        "--project",
        default=None,
        help=(
            "Project to run against. Defaults to the project bound to the "
            "checkout you are standing in."
        ),
    )
    parser.add_argument(
        "--file",
        default=None,
        help="Also write the rendered health report to PATH (human mode).",
    )
    parser.add_argument(
        "--db-path", dest="db_path", default=None, help="Optional DB path override."
    )
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
    # One sink for the whole run, whichever transport serves it: every
    # check this process executes emits through the shared executor, and
    # a relayed batch's verdicts are rendered from its rows as they land.
    with stream_progress_to_stderr():
        if _active_transport_is_https():
            from yoke_cli.commands.adapters.doctor_https_compose import (
                resolve_operator_project,
            )

            payload["project"] = resolve_operator_project(str(payload["project"]))
            return _dispatch_chunked(
                payload=payload,
                session_id=parsed.session_id,
                json_mode=parsed.json_mode,
                report_file=parsed.file,
            )
        return _dispatch_in_process(
            payload=payload,
            session_id=parsed.session_id,
            json_mode=parsed.json_mode,
            report_file=parsed.file,
        )


def _dispatch_in_process(
    *,
    payload: Dict[str, Any],
    session_id: str | None,
    json_mode: bool,
    report_file: str | None,
) -> int:
    """Run the checks in this process, one dispatch for the whole roster.

    A non-https connection dispatches in-process, so the handler's check
    loop runs under the caller's progress sink and streams each verdict
    without the client having to chunk the roster to see one.
    """
    ensure_handlers_loaded()
    response = call_dispatcher(
        function_id="doctor.run.run",
        target=TargetRef(kind="global"),
        payload=payload,
        actor=build_actor(session_id=session_id),
        timeout_s=DOCTOR_RUN_READ_TIMEOUT_S,
    )
    return emit_doctor_response(
        response, json_mode=json_mode, report_file=report_file
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
    report_file: str | None,
) -> int:
    from yoke_cli.commands.adapters.doctor_https_run import dispatch_chunked

    return dispatch_chunked(
        payload=payload,
        session_id=session_id,
        json_mode=json_mode,
        chunk_max_checks=DOCTOR_CHUNK_MAX_CHECKS,
        timeout_s=DOCTOR_RUN_READ_TIMEOUT_S,
        report_file=report_file,
    )
