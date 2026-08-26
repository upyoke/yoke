"""Service-client commands for the shared-operation claim primitive.

Wires the human-operator recovery path (``coordination-claim-release``)
plus the diagnostic surfaces (``coordination-claim-acquire``,
``-heartbeat``, ``-list``) used by doctor and operators to inspect
shared-operation claims without dropping to raw SQL. Migration rehearsal
scopes by ``LIVE_DB_MIGRATION:<model_name>`` and takes its claim
internally; the acquire/heartbeat commands are for new shared-operation
consumers and operator diagnostics, not as a bypass of the governed
runner.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict

from yoke_core.domain.cli_text_file import add_text_file_pair, resolve_text_file
from yoke_core.api.service_client_shared import _get_db_readwrite


def cmd_coordination_claim_release(args: list[str]) -> int:
    """Human-only operator override to release a stranded claim."""
    parser = argparse.ArgumentParser(
        prog="coordination-claim-release", add_help=False
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--key", required=True)
    reason_group = parser.add_mutually_exclusive_group(required=True)
    add_text_file_pair(reason_group, "--reason", "--reason-file", dest="reason")
    reason_group.add_argument("--intent", dest="reason")
    parser.add_argument("--session-id", default=None)

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print(
            "Usage: coordination-claim-release --project P --key K --reason R "
            "[--session-id S]",
            file=sys.stderr,
        )
        return 2
    try:
        reason = resolve_text_file(parsed.reason, parsed.reason_file, "--reason-file")
    except ValueError as exc:
        return _emit_error("USAGE", str(exc))

    from yoke_core.domain.coordination_claims import (
        CoordinationClaimError,
        CoordinationClaimHookContextError,
        CoordinationClaimNotFoundError,
    )
    from yoke_core.domain.coordination_claims_operator import operator_release

    conn = _get_db_readwrite()
    try:
        try:
            result = operator_release(
                conn,
                project_id=parsed.project,
                key=parsed.key,
                operator_reason=reason,
                session_id=parsed.session_id,
            )
        except CoordinationClaimHookContextError as exc:
            return _emit_error("HOOK_CONTEXT", str(exc))
        except CoordinationClaimNotFoundError as exc:
            return _emit_error("NOT_FOUND", str(exc))
        except CoordinationClaimError as exc:
            return _emit_error("CLAIM_ERROR", str(exc))
    finally:
        conn.close()

    print(json.dumps({"success": True, **result}))
    return 0


def cmd_coordination_claim_acquire(args: list[str]) -> int:
    """Acquire a coordination claim for a shared-operation consumer.

    Returns a JSON envelope with the claim's id and timestamps. Live DB
    migration takes its own claim internally during the governed apply
    path; this command is for *additional* shared-operation consumers and
    for operator-driven diagnostics.
    """
    parser = argparse.ArgumentParser(
        prog="coordination-claim-acquire", add_help=False
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--item", type=int, default=None)

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print(
            "Usage: coordination-claim-acquire --project P --key K "
            "--session-id S [--item N]",
            file=sys.stderr,
        )
        return 2

    from yoke_core.domain.coordination_claim_keys import (
        CoordinationKeyError,
        target_for_key,
    )
    from yoke_core.domain.coordination_claims import (
        CoordinationClaimHeldError,
        CoordinationClaimStaleHolderError,
        acquire,
    )
    from yoke_core.domain.project_identity import resolve_project_id

    conn = _get_db_readwrite()
    try:
        try:
            target = target_for_key(
                parsed.key,
                project_id=resolve_project_id(conn, parsed.project),
                item_id=parsed.item,
            )
        except (CoordinationKeyError, ValueError) as exc:
            return _emit_error("USAGE", str(exc))
        try:
            claim = acquire(conn, target, parsed.session_id)
        except CoordinationClaimStaleHolderError as exc:
            return _emit_error("STALE_HOLDER", str(exc))
        except CoordinationClaimHeldError as exc:
            return _emit_error("HELD", str(exc))
    finally:
        conn.close()

    print(json.dumps({"success": True, "claim": _claim_to_dict(claim)}))
    return 0


def cmd_coordination_claim_heartbeat(args: list[str]) -> int:
    """Refresh the heartbeat on a held coordination claim."""
    parser = argparse.ArgumentParser(
        prog="coordination-claim-heartbeat", add_help=False
    )
    parser.add_argument("--claim-id", type=int, required=True)

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print(
            "Usage: coordination-claim-heartbeat --claim-id N",
            file=sys.stderr,
        )
        return 2

    from yoke_core.domain.coordination_claims import (
        CoordinationClaimNotFoundError,
        CoordinationClaimReleasedError,
        heartbeat,
    )

    conn = _get_db_readwrite()
    try:
        try:
            claim = heartbeat(conn, parsed.claim_id)
        except CoordinationClaimNotFoundError as exc:
            return _emit_error("NOT_FOUND", str(exc))
        except CoordinationClaimReleasedError as exc:
            return _emit_error("RELEASED", str(exc))
    finally:
        conn.close()

    print(json.dumps({"success": True, "claim": _claim_to_dict(claim)}))
    return 0


def cmd_coordination_claim_list(args: list[str]) -> int:
    """List shared-operation claims with optional filters."""
    parser = argparse.ArgumentParser(
        prog="coordination-claim-list", add_help=False
    )
    parser.add_argument("--project", default=None)
    parser.add_argument("--key", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--active-only", action="store_true")

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print(
            "Usage: coordination-claim-list [--project P] [--key K] "
            "[--session-id S] [--active-only]",
            file=sys.stderr,
        )
        return 2

    from yoke_core.domain.coordination_claims_listing import list_claims

    conn = _get_db_readwrite()
    try:
        claims = list_claims(
            conn,
            project_id=parsed.project,
            key=parsed.key,
            session_id=parsed.session_id,
            active_only=parsed.active_only,
        )
    finally:
        conn.close()

    print(json.dumps({
        "success": True,
        "claims": [_claim_to_dict(claim) for claim in claims],
    }))
    return 0


def _emit_error(code: str, message: str) -> int:
    print(
        json.dumps({"success": False, "code": code, "message": message}),
        file=sys.stderr,
    )
    return 1


def _claim_to_dict(claim: Any) -> Dict[str, Any]:
    from yoke_core.domain.coordination_claim_record import claim_as_dict

    return claim_as_dict(claim)


COORDINATION_CLAIM_COMMANDS: Dict[str, Any] = {
    "coordination-claim-release": cmd_coordination_claim_release,
    "coordination-claim-acquire": cmd_coordination_claim_acquire,
    "coordination-claim-heartbeat": cmd_coordination_claim_heartbeat,
    "coordination-claim-list": cmd_coordination_claim_list,
}


__all__ = [
    "COORDINATION_CLAIM_COMMANDS",
    "cmd_coordination_claim_acquire",
    "cmd_coordination_claim_heartbeat",
    "cmd_coordination_claim_list",
    "cmd_coordination_claim_release",
]
