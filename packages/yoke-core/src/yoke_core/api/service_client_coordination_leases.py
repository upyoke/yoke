"""Service-client commands for the coordination-lease primitive.

Wires the human-operator recovery path (``coordination-lease-release``) plus
the diagnostic surfaces (``coordination-lease-acquire``, ``-heartbeat``,
``-list``) used by doctor and operators to inspect shared-operation leases
without dropping to raw SQL. The migration consumer scopes by
``LIVE_DB_MIGRATION:<model_name>`` and acquires its lease internally during
governed live-apply; the acquire/heartbeat CLIs are intended for new
shared-operation consumers and for operator diagnostics, not as a bypass of
the governed runner.
"""

from __future__ import annotations

import argparse
import json
import sys
from typing import Any, Dict, List

from yoke_core.domain.cli_text_file import add_text_file_pair, resolve_text_file
from yoke_core.api.service_client_shared import _get_db_readwrite


def cmd_coordination_lease_release(args: list[str]) -> int:
    """Human-only operator override to release a stranded coordination lease."""
    parser = argparse.ArgumentParser(
        prog="coordination-lease-release", add_help=False
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
            "Usage: coordination-lease-release --project P --key K --reason R "
            "[--session-id S]",
            file=sys.stderr,
        )
        return 2
    try:
        reason = resolve_text_file(parsed.reason, parsed.reason_file, "--reason-file")
    except ValueError as exc:
        return _emit_error("USAGE", str(exc))

    from yoke_core.domain.coordination_leases import (
        LeaseError,
        LeaseHookContextError,
        LeaseNotFoundError,
        operator_release,
    )

    conn = _get_db_readwrite()
    try:
        try:
            result = operator_release(
                conn,
                project_id=parsed.project,
                lease_key=parsed.key,
                operator_reason=reason,
                session_id=parsed.session_id,
            )
        except LeaseHookContextError as exc:
            return _emit_error("HOOK_CONTEXT", str(exc))
        except LeaseNotFoundError as exc:
            return _emit_error("NOT_FOUND", str(exc))
        except LeaseError as exc:
            return _emit_error("LEASE_ERROR", str(exc))
    finally:
        conn.close()

    print(json.dumps({"success": True, **result}))
    return 0


def cmd_coordination_lease_acquire(args: list[str]) -> int:
    """Acquire a coordination lease for a new shared-operation consumer.

    Returns a JSON envelope with the acquired lease's id and timestamps.
    Live DB migration acquires its own lease internally during the governed
    apply path; this command is for *additional* shared-operation consumers
    and for operator-driven diagnostics.
    """
    parser = argparse.ArgumentParser(
        prog="coordination-lease-acquire", add_help=False
    )
    parser.add_argument("--project", required=True)
    parser.add_argument("--key", required=True)
    parser.add_argument("--session-id", required=True)
    parser.add_argument("--actor-id", default=None)

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print(
            "Usage: coordination-lease-acquire --project P --key K "
            "--session-id S [--actor-id A]",
            file=sys.stderr,
        )
        return 2

    from yoke_core.domain.coordination_leases import (
        LeaseHeldError,
        acquire_lease,
    )

    conn = _get_db_readwrite()
    try:
        try:
            lease = acquire_lease(
                conn, parsed.project, parsed.key, parsed.session_id,
                actor_id=parsed.actor_id,
            )
        except LeaseHeldError as exc:
            return _emit_error("HELD", str(exc))
    finally:
        conn.close()

    print(json.dumps({"success": True, "lease": _lease_to_dict(lease)}))
    return 0


def cmd_coordination_lease_heartbeat(args: list[str]) -> int:
    """Refresh ``heartbeat_at`` on a held lease."""
    parser = argparse.ArgumentParser(
        prog="coordination-lease-heartbeat", add_help=False
    )
    parser.add_argument("--lease-id", type=int, required=True)

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print(
            "Usage: coordination-lease-heartbeat --lease-id N",
            file=sys.stderr,
        )
        return 2

    from yoke_core.domain.coordination_leases import (
        LeaseNotFoundError,
        LeaseReleasedError,
        heartbeat_lease,
    )

    conn = _get_db_readwrite()
    try:
        try:
            lease = heartbeat_lease(conn, parsed.lease_id)
        except LeaseNotFoundError as exc:
            return _emit_error("NOT_FOUND", str(exc))
        except LeaseReleasedError as exc:
            return _emit_error("RELEASED", str(exc))
    finally:
        conn.close()

    print(json.dumps({"success": True, "lease": _lease_to_dict(lease)}))
    return 0


def cmd_coordination_lease_list(args: list[str]) -> int:
    """List coordination leases with optional filters."""
    parser = argparse.ArgumentParser(
        prog="coordination-lease-list", add_help=False
    )
    parser.add_argument("--project", default=None)
    parser.add_argument("--key", default=None)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--active-only", action="store_true")

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print(
            "Usage: coordination-lease-list [--project P] [--key K] "
            "[--session-id S] [--active-only]",
            file=sys.stderr,
        )
        return 2

    from yoke_core.domain.coordination_leases import list_leases

    conn = _get_db_readwrite()
    try:
        leases = list_leases(
            conn,
            project_id=parsed.project,
            lease_key=parsed.key,
            session_id=parsed.session_id,
            active_only=parsed.active_only,
        )
    finally:
        conn.close()

    print(json.dumps({
        "success": True,
        "leases": [_lease_to_dict(lease) for lease in leases],
    }))
    return 0


def _emit_error(code: str, message: str) -> int:
    print(
        json.dumps({"success": False, "code": code, "message": message}),
        file=sys.stderr,
    )
    return 1


def _lease_to_dict(lease: Any) -> Dict[str, Any]:
    return {
        "id": lease.id,
        "project_id": lease.project_id,
        "lease_key": lease.lease_key,
        "session_id": lease.session_id,
        "actor_id": lease.actor_id,
        "acquired_at": lease.acquired_at,
        "heartbeat_at": lease.heartbeat_at,
        "released_at": lease.released_at,
        "release_reason": lease.release_reason,
    }


COORDINATION_LEASE_COMMANDS: Dict[str, Any] = {
    "coordination-lease-release": cmd_coordination_lease_release,
    "coordination-lease-acquire": cmd_coordination_lease_acquire,
    "coordination-lease-heartbeat": cmd_coordination_lease_heartbeat,
    "coordination-lease-list": cmd_coordination_lease_list,
}


__all__ = [
    "COORDINATION_LEASE_COMMANDS",
    "cmd_coordination_lease_acquire",
    "cmd_coordination_lease_heartbeat",
    "cmd_coordination_lease_list",
    "cmd_coordination_lease_release",
]
