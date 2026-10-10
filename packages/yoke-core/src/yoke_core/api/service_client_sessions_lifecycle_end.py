"""Session-end command handlers — explicit end and best-effort end-if-empty."""

from __future__ import annotations

from yoke_core.domain.json_helper import dumps_compact
import sys

from yoke_core.api.service_client_shared import (
    SESSION_REQUIRED_ERROR,
    _get_db_readwrite,
    _resolve_session_id,
    domain_end_session,
    domain_end_session_if_empty,
)


def cmd_session_end(args: list[str]) -> int:
    """Explicitly end a session and release its liveness-bound claims."""
    import argparse

    parser = argparse.ArgumentParser(prog="session-end", add_help=True)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--force", action="store_true", default=False)
    parser.add_argument("--release-claims", action="store_true", default=False)
    try:
        parsed = parser.parse_args(args)
    except SystemExit as exc:
        # --help raises SystemExit(0) after printing usage; let it
        # propagate as a clean exit. Argparse parse failures stay 2.
        if exc.code == 0:
            return 0
        print(
            "Usage: session-end [--session-id S] [--force] [--release-claims]",
            file=sys.stderr,
        )
        return 2

    parsed.session_id = _resolve_session_id(parsed.session_id)
    if not parsed.session_id:
        print(SESSION_REQUIRED_ERROR, file=sys.stderr)
        return 2

    conn = _get_db_readwrite()
    try:
        from yoke_core.domain.sessions import SessionError

        try:
            result = domain_end_session(
                conn,
                parsed.session_id,
                force=parsed.force,
                release_claims=parsed.release_claims,
            )
            released_claims = result.pop("released_claims", None)
            response = {"success": True, "session": result}
            if released_claims:
                response["released_claims"] = released_claims
            print(dumps_compact(response))
        except SessionError as exc:
            print(
                dumps_compact(
                    {
                        "success": True,
                        "already_ended": True,
                        "code": exc.code,
                        "message": exc.message,
                    }
                )
            )
        return 0
    finally:
        conn.close()


def cmd_session_end_if_empty(args: list[str]) -> int:
    """End a session only when it holds no active unreleased claims.

    Usage: session-end-if-empty --session-id S

    Best-effort cleanup helper for harness stop/session-end hooks.
    Never fails for NOT_FOUND or already-ended sessions; claims are preserved.
    Prints result JSON to stdout and exits 0 on success, 2 on usage error.
    """
    import argparse

    parser = argparse.ArgumentParser(
        prog="session-end-if-empty",
        add_help=False,
    )
    parser.add_argument("--session-id", default=None)

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print("Usage: session-end-if-empty [--session-id S]", file=sys.stderr)
        return 2

    parsed.session_id = _resolve_session_id(parsed.session_id)
    if not parsed.session_id:
        print(SESSION_REQUIRED_ERROR, file=sys.stderr)
        return 2

    conn = _get_db_readwrite()
    try:
        result = domain_end_session_if_empty(conn, parsed.session_id)
        print(dumps_compact({"success": True, **result}))
        return 0
    finally:
        conn.close()


__all__ = ["cmd_session_end", "cmd_session_end_if_empty"]
