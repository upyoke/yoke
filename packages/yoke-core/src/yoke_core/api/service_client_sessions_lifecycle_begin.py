"""Session-begin command handler — unified session lifecycle creation."""

from __future__ import annotations

import json
import sys
from pathlib import Path

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


def begin_session(
    conn,
    *,
    session_id: str,
    executor: str,
    provider: str,
    model: str,
    workspace: str,
    project_id: int,
    mode: str = "wait",
    entrypoint: str | None = None,
    executor_version: str | None = None,
    machine_id: str | None = None,
    native_thread_id: str | None = None,
    actor_id: int | None = None,
) -> dict:
    """Register (or idempotently refresh) a session row; return a result dict.

    Resolves the execution lane from the project's routing config and
    registers the session — the identical steps the operator-debug
    ``session-begin`` command and the transport-keyed ``sessions.begin``
    function handler both need. The already-registered case returns a
    success dict rather than raising; every other :class:`SessionError`
    propagates so callers can shape their own error response.

    ``actor_id`` is the caller's authenticated actor when the transport
    verified one; without it registration binds the universe's operating
    actor rather than storing NULL.

    ``executor`` is passed through verbatim.
    :func:`yoke_core.domain.sessions_lifecycle_canonicalize.canonicalize_executor`
    is the single site that splits it into the stored canonical id and
    display alias, and it prefers a surface-specific value over one composed
    from the entrypoint. Composing here first would destroy that preference:
    a ``codex-desktop`` surface plus a ``dash`` entrypoint would arrive as
    ``codex-dash``, and the surface the session actually ran on would be
    unrecoverable. Lane routing reads the same verbatim value, which matches
    both exact surface keys and family wildcards in the routing config.
    """
    from yoke_core.domain.sessions import SessionError, register_session

    routing_config = _load_routing_config(conn=conn, project_id=project_id)
    resolved_lane = resolve_execution_lane(
        executor=executor,
        explicit_lane=None,
        routing_config=routing_config,
    )
    try:
        result = register_session(
            conn,
            session_id=session_id,
            executor=executor,
            provider=provider,
            model=model,
            workspace=workspace,
            project_id=project_id,
            mode=mode,
            execution_lane=resolved_lane,
            entrypoint=entrypoint,
            executor_version=executor_version,
            machine_id=machine_id,
            native_thread_id=native_thread_id,
            actor_id=actor_id,
        )
    except SessionError as exc:
        if exc.code == "SESSION_EXISTS":
            return {
                "success": True,
                "already_registered": True,
                "session_id": session_id,
            }
        raise
    return {"success": True, "session": result}


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
    parser.add_argument("--executor-version", default=None)
    parser.add_argument("--machine-id", default=None)
    parser.add_argument("--native-thread-id", default=None)

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
        from yoke_core.domain.sessions import SessionError
        try:
            result = begin_session(
                conn,
                session_id=parsed.session_id,
                executor=parsed.executor,
                provider=parsed.provider,
                model=parsed.model,
                workspace=parsed.workspace,
                project_id=resolved_project_id,
                mode=parsed.mode,
                entrypoint=parsed.entrypoint,
                executor_version=parsed.executor_version,
                machine_id=parsed.machine_id,
                native_thread_id=parsed.native_thread_id,
            )
            print(json.dumps(result, default=str))
        except SessionError as exc:
            print(json.dumps({
                "success": False,
                "code": exc.code,
                "message": exc.message,
            }), file=sys.stderr)
            return 1
        return 0
    finally:
        conn.close()


__all__ = ["begin_session", "cmd_session_begin"]
