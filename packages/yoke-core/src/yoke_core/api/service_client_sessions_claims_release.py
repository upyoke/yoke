"""Claim release command handlers (legacy shape minus item-named CLIs).

Covers:
- ``release-all-claims`` — best-effort release of every active claim on a session
- ``claim-release`` — human-only operator override for stranded claims
- ``release-done-claims`` — release any unreleased claims on a now-done item

The execution-owned single-claim release moved to the typed-target
``release-work-claim`` surface in
:mod:`yoke_core.api.service_client_work_claims`.
"""

from __future__ import annotations

import json
import subprocess
import sys

from yoke_core.api.service_client_shared import (
    SESSION_REQUIRED_ERROR,
    _get_db_readonly,
    _get_db_readwrite,
    _resolve_session_id,
    _subprocess_service_env,
    domain_release_done_claims,
    normalize_claim_item_id,
)


def cmd_release_all_claims(args: list[str]) -> int:
    """Release all active claims for a session.

    Usage: release-all-claims --session-id S --reason R

    Best-effort: if the session is unknown or not active, exits 0 silently.
    Does NOT end the session.
    Prints JSON result to stdout.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="release-all-claims", add_help=False)
    parser.add_argument("--session-id", default=None)
    parser.add_argument(
        "--reason", "--intent",
        dest="reason", required=True,
    )

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print("Usage: release-all-claims [--session-id S] --reason R",
              file=sys.stderr)
        return 2

    parsed.session_id = _resolve_session_id(parsed.session_id)
    if not parsed.session_id:
        print(SESSION_REQUIRED_ERROR, file=sys.stderr)
        return 2

    conn = _get_db_readonly()
    try:
        row = conn.execute(
            "SELECT ended_at FROM harness_sessions WHERE session_id = %s",
            (parsed.session_id,),
        ).fetchone()
    finally:
        conn.close()

    if row is None or row["ended_at"] is not None:
        print(json.dumps({"success": True, "no_session": True}))
        return 0

    proc = subprocess.run(
        [sys.executable, "-m", "runtime.harness.harness_sessions",
         "release-all", parsed.session_id, parsed.reason],
        capture_output=True,
        text=True,
        env=_subprocess_service_env(),
    )

    if proc.returncode == 0:
        print(json.dumps({"success": True, "released": proc.stdout.strip()}))
        return 0
    else:
        print(json.dumps({
            "success": False,
            "error": proc.stderr.strip(),
        }), file=sys.stderr)
        return 1


def cmd_claim_release(args: list[str]) -> int:
    """Human-only operator override to release a stranded claim.

    Usage: claim-release (--item-id I | --item I) --reason R \\
           [--session-id S] [--claim-id N]

    ``--item`` and ``--item-id`` are synonyms. ``--help`` exits
    0 with the usage line on stdout. This command is NOT for automated
    hook use; it rejects invocation when YOKE_HOOK_EVENT is set in
    the environment. Prints result JSON to stdout.
    """
    import argparse

    from yoke_core.domain.sessions import (
        SessionError,
        operator_override_release_claim,
    )

    parser = argparse.ArgumentParser(prog="claim-release", add_help=True)
    # ``--item`` and ``--item-id`` are synonyms. Argparse routes
    # both into the same ``item_id`` attr; the parser-level mutual
    # exclusion ensures exactly one is supplied (still required).
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--item-id", dest="item_id")
    target.add_argument("--item", dest="item_id")
    parser.add_argument(
        "--reason", "--intent",
        dest="reason", required=True,
    )
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--claim-id", type=int, default=None)

    try:
        parsed = parser.parse_args(args)
    except SystemExit as exc:
        # ``--help`` raises SystemExit(0) AFTER printing usage to stdout;
        # propagate as-is so the help path stays clean. Other
        # parse failures fall through to the legacy usage hint on stderr.
        if exc.code == 0:
            return 0
        print(
            "Usage: claim-release (--item-id I | --item I) --reason R "
            "[--session-id S] [--claim-id N]",
            file=sys.stderr,
        )
        return 2

    conn = _get_db_readwrite()
    try:
        result = operator_override_release_claim(
            conn,
            parsed.item_id,
            parsed.reason,
            session_id=parsed.session_id,
            claim_id=parsed.claim_id,
        )
        print(json.dumps({"success": True, **result}))
        return 0
    except SessionError as exc:
        print(json.dumps({
            "success": False,
            "code": exc.code,
            "message": exc.message,
        }))
        return 1
    finally:
        conn.close()


def cmd_release_done_claims(args: list[str]) -> int:
    """Release all unreleased claims on an item that has transitioned to done.

    Usage: release-done-claims --item-id YOK-N

    Prints JSON with the number of claims released.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="release-done-claims", add_help=False)
    parser.add_argument("--item-id", required=True)

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print("Usage: release-done-claims --item-id YOK-N", file=sys.stderr)
        return 2
    parsed.item_id = normalize_claim_item_id(parsed.item_id)

    conn = _get_db_readwrite()
    try:
        released = domain_release_done_claims(conn, parsed.item_id)
        print(json.dumps({"success": True, "released": released, "item_id": parsed.item_id}))
        return 0
    finally:
        conn.close()


__all__ = [
    "cmd_release_all_claims",
    "cmd_claim_release",
    "cmd_release_done_claims",
]
