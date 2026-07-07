"""Session chain-checkpoint command handlers.

Owns the CLI surface for ``service-client session-checkpoint`` (write) and
``service-client session-checkpoint-read`` (read), persisted on the session's
``offer_envelope`` JSON column.
"""

from __future__ import annotations

import json
import sys

from yoke_core.api.service_client_shared import (
    SESSION_REQUIRED_ERROR,
    _get_db_readonly,
    _get_db_readwrite,
    _resolve_session_id,
    domain_read_checkpoint,
    domain_update_checkpoint,
)


def cmd_session_checkpoint(args: list[str]) -> int:
    """Persist a post-handler chain checkpoint on the session's offer_envelope.

    Usage: session-checkpoint --session-id S --step N --action A --chainable BOOL
                              [--item-id I] [--task-num T] [--outcome O]

    Prints the checkpoint JSON to stdout.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="session-checkpoint", add_help=False)
    parser.add_argument("--session-id", default=None)
    parser.add_argument("--step", type=int, required=True)
    parser.add_argument("--action", required=True)
    parser.add_argument("--chainable", required=True)
    parser.add_argument("--item-id", default=None)
    parser.add_argument("--task-num", type=int, default=None)
    parser.add_argument("--outcome", default="completed")
    parser.add_argument("--status", default=None)
    parser.add_argument("--required-path", default=None)
    parser.add_argument("--pre-status", default=None)

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print("Usage: session-checkpoint [--session-id S] --step N --action A --chainable BOOL [--item-id I] [--task-num T] [--outcome O] [--status S] [--required-path P] [--pre-status PS]", file=sys.stderr)
        return 2

    parsed.session_id = _resolve_session_id(parsed.session_id)
    if not parsed.session_id:
        print(SESSION_REQUIRED_ERROR, file=sys.stderr)
        return 2

    chainable = parsed.chainable.lower() in ("true", "1", "yes")

    conn = _get_db_readwrite()
    try:
        from yoke_core.domain.sessions import SessionError
        try:
            checkpoint = domain_update_checkpoint(
                conn,
                parsed.session_id,
                step=parsed.step,
                action=parsed.action,
                chainable=chainable,
                handler_outcome=parsed.outcome,
                item_id=parsed.item_id,
                task_num=parsed.task_num,
                status=parsed.status,
                required_path=parsed.required_path,
                pre_status=parsed.pre_status,
            )
            print(json.dumps(checkpoint))
            return 0
        except SessionError as exc:
            print(json.dumps({"error": exc.code, "message": exc.message}), file=sys.stderr)
            return 1
    finally:
        conn.close()


def cmd_session_checkpoint_read(args: list[str]) -> int:
    """Read the persisted chain checkpoint from a session's offer_envelope.

    Usage: session-checkpoint-read --session-id S

    Prints the checkpoint JSON to stdout, or {} if no checkpoint exists.
    """
    import argparse

    parser = argparse.ArgumentParser(prog="session-checkpoint-read", add_help=False)
    parser.add_argument("--session-id", default=None)

    try:
        parsed = parser.parse_args(args)
    except SystemExit:
        print("Usage: session-checkpoint-read [--session-id S]", file=sys.stderr)
        return 2

    parsed.session_id = _resolve_session_id(parsed.session_id)
    if not parsed.session_id:
        print(SESSION_REQUIRED_ERROR, file=sys.stderr)
        return 2

    conn = _get_db_readonly()
    try:
        checkpoint = domain_read_checkpoint(conn, parsed.session_id)
        print(json.dumps(checkpoint or {}))
        return 0
    finally:
        conn.close()


__all__ = [
    "cmd_session_checkpoint",
    "cmd_session_checkpoint_read",
]
