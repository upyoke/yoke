"""Session-begin command handler — unified session lifecycle creation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

from yoke_harness.hooks.identity import compose_executor_from_entrypoint

from yoke_core.api.service_client_shared import (
    SESSION_REQUIRED_ERROR,
    _get_db_readwrite,
    _load_routing_config,
    _resolve_session_id,
    resolve_execution_lane,
)


def _project_id_from_args(explicit: str | None, workspace: str) -> int | None:
    if explicit:
        try:
            project_id = int(explicit)
        except (TypeError, ValueError):
            return None
        return project_id if project_id > 0 else None
    try:
        from yoke_core.domain import machine_config

        return machine_config.project_id(Path(workspace))
    except Exception:
        return None


def cmd_session_begin(args: list[str]) -> int:
    """Begin (or idempotently refresh) a session in harness_sessions.

    Usage: session-begin --session-id S --executor E --provider P
                         --model M --workspace W [--mode MODE]

    Idempotent: if the session already exists and is active, returns success
    without error. This allows hooks to call session-begin on every prompt
    without worrying about duplicates.

    Prints result JSON to stdout.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="session-begin", add_help=False)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--executor", required=True)
    parser.add_argument("--provider", required=True)
    parser.add_argument("--model", required=True)
    parser.add_argument("--workspace", required=True)
    parser.add_argument("--project-id", default=None)
    parser.add_argument("--mode", default="wait")
    parser.add_argument("--entrypoint", default=None)

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print("Usage: session-begin [--session-id S] --executor E "
              "--provider P --model M --workspace W [--mode MODE]",
              file=sys.stderr)
        return 2

    parsed.session_id = _resolve_session_id(parsed.session_id)
    if not parsed.session_id:
        print(SESSION_REQUIRED_ERROR, file=sys.stderr)
        return 2

    parsed.executor = compose_executor_from_entrypoint(
        parsed.executor,
        parsed.entrypoint,
    )

    resolved_project_id = _project_id_from_args(parsed.project_id, parsed.workspace)
    if resolved_project_id is None:
        print(
            "Session registration requires a project id. Run Yoke setup for "
            "this checkout or pass --project-id.",
            file=sys.stderr,
        )
        return 2

    conn = _get_db_readwrite()
    try:
        routing_config = _load_routing_config(
            conn=conn,
            project_id=resolved_project_id,
        )
        resolved_lane = resolve_execution_lane(
            executor=parsed.executor,
            explicit_lane=None,
            routing_config=routing_config,
        )
        from yoke_core.domain.sessions import register_session, SessionError
        try:
            result = register_session(
                conn,
                session_id=parsed.session_id,
                executor=parsed.executor,
                provider=parsed.provider,
                model=parsed.model,
                workspace=parsed.workspace,
                project_id=resolved_project_id,
                mode=parsed.mode,
                execution_lane=resolved_lane,
                entrypoint=parsed.entrypoint,
            )
            print(json.dumps({"success": True, "session": result}, default=str))
        except SessionError as exc:
            if exc.code == "SESSION_EXISTS":
                print(json.dumps({
                    "success": True,
                    "already_registered": True,
                    "session_id": parsed.session_id,
                }))
            else:
                print(json.dumps({
                    "success": False,
                    "code": exc.code,
                    "message": exc.message,
                }), file=sys.stderr)
                return 1
        return 0
    finally:
        conn.close()


__all__ = ["cmd_session_begin"]
