"""Session-end command handlers — explicit end and best-effort end-if-empty."""

from __future__ import annotations

import json
import sys

from yoke_core.api.service_client_shared import (
    SESSION_REQUIRED_ERROR,
    _get_db_readwrite,
    _resolve_session_id,
    domain_end_session,
    domain_end_session_if_empty,
)


def cmd_session_end(args: list[str]) -> int:
    """End a session, marking it as ended.

    Usage: session-end --session-id S [--force] [--release-claims]
                       [--override-chain-end --chain-end-rationale TEXT]

    Best-effort for NOT_FOUND and SESSION_ENDED: exits 0.
    CHAIN_PENDING: exits 1 unless ``--override-chain-end`` is paired with a
    non-empty ``--chain-end-rationale``. The override emits
    ``ChainDeclineOverridden``.
    No-flags (default): active work-claims are auto-released with
    ``release_reason='session_ended'`` before the session ends. The
    success payload carries ``released_claims: [{claim_id, target_kind,
    item_id|epic_id+task_num|process_key+conflict_group}, ...]`` so
    callers can audit what was cleaned up; absent when no claims were
    held. CHAIN_PENDING still blocks honest loop exits with budget
    remaining.
    With --release-claims, active claims are auto-released before ending
    via the destructive-guard branch (hook path).
    TRANSIENT_END_DEFERRED: exits 1 when ``--release-claims`` is supplied
    but the destructive guard classified the signal as transient (fresh
    heartbeat or chain budget remaining). ``HarnessSessionEndDeferred`` has
    already been emitted; the session row is unchanged. Operator must use
    ``claim-release`` to free a stranded claim or wait for the recovery
    window to elapse. This is reported as ``success=false`` so callers
    cannot mistake a deferred end for a genuine end.
    Prints result JSON to stdout.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="session-end", add_help=True)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--force", action="store_true", default=False)
    parser.add_argument("--release-claims", action="store_true", default=False)
    parser.add_argument(
        "--override-chain-end",
        action="store_true",
        default=False,
        help="Bypass the CHAIN_PENDING guard. Requires --chain-end-rationale.",
    )
    parser.add_argument(
        "--chain-end-rationale",
        default=None,
        help="Operator rationale recorded with ChainDeclineOverridden.",
    )

    try:
        parsed = parser.parse_args(args)
    except SystemExit as exc:
        # --help raises SystemExit(0) after printing usage; let it
        # propagate as a clean exit. Argparse parse failures stay 2.
        if exc.code == 0:
            return 0
        print(
            "Usage: session-end [--session-id S] [--force] [--release-claims]"
            " [--override-chain-end --chain-end-rationale TEXT]",
            file=sys.stderr,
        )
        return 2

    parsed.session_id = _resolve_session_id(parsed.session_id)
    if not parsed.session_id:
        print(SESSION_REQUIRED_ERROR, file=sys.stderr)
        return 2

    if parsed.override_chain_end and not (
        parsed.chain_end_rationale and parsed.chain_end_rationale.strip()
    ):
        print(json.dumps({
            "success": False,
            "code": "OVERRIDE_RATIONALE_REQUIRED",
            "message": (
                "--override-chain-end requires a non-empty --chain-end-rationale."
            ),
        }))
        return 2

    conn = _get_db_readwrite()
    try:
        from yoke_core.domain.sessions import SessionError
        try:
            result = domain_end_session(
                conn, parsed.session_id,
                force=parsed.force,
                release_claims=parsed.release_claims,
                override_chain_end=parsed.override_chain_end,
                chain_end_rationale=parsed.chain_end_rationale,
            )
            released_claims = result.pop("released_claims", None)
            response = {"success": True, "session": result}
            if released_claims:
                response["released_claims"] = released_claims
            print(json.dumps(response, default=str))
        except SessionError as exc:
            if exc.code in (
                "CHAIN_PENDING",
                "TRANSIENT_END_DEFERRED",
            ):
                print(json.dumps({
                    "success": False,
                    "code": exc.code,
                    "message": exc.message,
                }))
                return 1
            print(json.dumps({
                "success": True,
                "already_ended": True,
                "code": exc.code,
                "message": exc.message,
            }))
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
        print(json.dumps({"success": True, **result}, default=str))
        return 0
    finally:
        conn.close()


__all__ = ["cmd_session_end", "cmd_session_end_if_empty"]
