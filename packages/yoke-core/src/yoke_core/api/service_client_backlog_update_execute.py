"""Prepare programmatic item field updates and emit their public receipt."""

from __future__ import annotations

import io
import json
import sys

from yoke_core.api.service_client_shared import _resolve_session_id
from yoke_core.api.service_client_force_finalize import run_force_finalize_handoff


def cmd_execute_update(args: list[str]) -> int:
    """Full item update: validate -> UPDATE -> side effects -> sync.

    Usage: execute-update <PREFIX-N> --field FIELD --value VALUE
                          [--done-nonce-verified] [--force] [--qa-bypass]
                          [--dry-run]

    Returns JSON result on stdout.
    """
    from yoke_core.domain import backlog

    if not args:
        print(
            "Usage: execute-update <PREFIX-N> --field FIELD --value VALUE ...",
            file=sys.stderr,
        )
        return 2

    try:
        from yoke_core.api.service_client_shared_session_resolver import (
            _parse_item_id_arg,
        )

        item_id = _parse_item_id_arg(args[0])
    except ValueError:
        print(
            json.dumps(
                {
                    "success": False,
                    "error": f"Item ref must be PREFIX-N, got '{args[0]}'",
                }
            )
        )
        return 1

    field = None
    value = None
    done_nonce_verified = False
    force_flag = False
    qa_bypass = False
    dry_run = False

    i = 1
    while i < len(args):
        if args[i] == "--field" and i + 1 < len(args):
            field = args[i + 1]
            i += 2
        elif args[i] == "--value" and i + 1 < len(args):
            value = args[i + 1]
            i += 2
        elif args[i] == "--done-nonce-verified":
            done_nonce_verified = True
            i += 1
        elif args[i] == "--force":
            force_flag = True
            i += 1
        elif args[i] == "--qa-bypass":
            qa_bypass = True
            i += 1
        elif args[i] == "--dry-run":
            dry_run = True
            i += 1
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            return 2

    if field is None or value is None:
        print(
            "Usage: execute-update <PREFIX-N> --field FIELD --value VALUE ...",
            file=sys.stderr,
        )
        return 2

    captured = io.StringIO()
    result = backlog.execute_update(
        item_id=item_id,
        field=field,
        value=value,
        done_nonce_verified=done_nonce_verified,
        force=force_flag,
        qa_bypass=qa_bypass,
        session_id=_resolve_session_id(None),
        dry_run=dry_run,
        out=captured,
    )
    result = dict(result)
    run_force_finalize_handoff(
        item_id=item_id,
        field=field,
        value=value,
        force=force_flag,
        dry_run=dry_run,
        result=result,
        out=captured,
    )
    result["log"] = captured.getvalue()
    from yoke_core.api.service_client_shared import _emit_backlog_result

    return _emit_backlog_result(result)
