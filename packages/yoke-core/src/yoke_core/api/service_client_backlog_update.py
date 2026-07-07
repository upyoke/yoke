"""Item field-update command handlers for the service_client CLI surface.

Owns ``execute-update`` (programmatic) and ``execute-update-cli`` (the public
``backlog-registry update`` shape including multi-field, structured-field, and
done-nonce paths).
"""

from __future__ import annotations

import io
import json
import os
import sys
from typing import Optional

from yoke_core.domain.structured_field_input import (
    ContentInputError,
    resolve_content_input,
)
from yoke_core.api.service_client_shared import (
    _consume_done_nonce,
    _emit_backlog_result,
    _isolated_test_mutation_error,
    _parse_item_id_arg,
    _resolve_session_id,
    _run_done_recovery,
    _update_requests_done,
)
from yoke_core.api.service_client_backlog_update_args import (
    normalize_update_args,
)
from yoke_core.api.service_client_backlog_update_dispatch import (
    _dispatch_structured_field_replace,
)
from yoke_core.api.service_client_force_finalize import run_force_finalize_handoff


def cmd_execute_update(args: list[str]) -> int:
    """Full item update: validate -> UPDATE -> side effects -> sync.

    Usage: execute-update <item-id> --field FIELD --value VALUE
                          [--done-nonce-verified] [--force] [--qa-bypass]
                          [--dry-run]

    Returns JSON result on stdout.
    """
    from yoke_core.domain import backlog

    if not args:
        print("Usage: execute-update <item-id> --field FIELD --value VALUE ...", file=sys.stderr)
        return 2

    try:
        item_id = int(args[0])
    except ValueError:
        print(json.dumps({"success": False, "error": f"Item ID must be integer, got '{args[0]}'"}))
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
            field = args[i + 1]; i += 2
        elif args[i] == "--value" and i + 1 < len(args):
            value = args[i + 1]; i += 2
        elif args[i] == "--done-nonce-verified":
            done_nonce_verified = True; i += 1
        elif args[i] == "--force":
            force_flag = True; i += 1
        elif args[i] == "--qa-bypass":
            qa_bypass = True; i += 1
        elif args[i] == "--dry-run":
            dry_run = True; i += 1
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            return 2

    if field is None or value is None:
        print("Usage: execute-update <item-id> --field FIELD --value VALUE ...", file=sys.stderr)
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
    print(json.dumps(result))
    return 0 if result.get("success") else 1


def cmd_execute_update_cli(args: list[str]) -> int:
    """Parse the public backlog-registry update CLI shape in Python.

    Supported forms:
      execute-update-cli <item-id> <field> <value>
      execute-update-cli <item-id> field1=value field2=value
      execute-update-cli <item-id> <structured-field> (--body-file PATH | --stdin)
                           [--force] [--source NAME]
      Global flags:
        --done-nonce-verified
        --qa-bypass
        --json   (structured-field path) — route through the function
                 dispatcher and emit the FunctionCallResponse envelope.
    """
    from yoke_core.domain import backlog

    isolation_error = _isolated_test_mutation_error()
    if isolation_error:
        return _emit_backlog_result({"success": False, "error": isolation_error})

    # Accept --id/--field/--value alongside positional form. The
    # normalizer rewrites named flags to positional before the legacy
    # parser runs so downstream branches (raw-body deny, structured-write
    # dispatch, done-nonce, GitHub/board sync) are reached unchanged.
    args = normalize_update_args(list(args))

    if len(args) < 2:
        print(
            "Usage: execute-update-cli <item-id> <field> <value> |"
            " <field=value>... | <structured-field> (--body-file <path> | --stdin)",
            file=sys.stderr,
        )
        return 2

    done_nonce_verified = False
    qa_bypass = os.environ.get("YOKE_QA_GATE_BYPASS", "0") == "1"
    no_rebuild = False
    json_mode = False
    positional_args: list[str] = []
    i = 0
    while i < len(args):
        token = args[i]
        if token == "--done-nonce-verified":
            done_nonce_verified = True
        elif token == "--qa-bypass":
            qa_bypass = True
        elif token == "--no-rebuild":
            no_rebuild = True
        elif token == "--json":
            json_mode = True
        else:
            positional_args.append(token)
        i += 1

    if len(positional_args) < 2:
        print(
            "Usage: execute-update-cli <item-id> <field> <value> |"
            " <field=value>... | <structured-field> (--body-file <path> | --stdin)",
            file=sys.stderr,
        )
        return 2

    try:
        item_id = _parse_item_id_arg(positional_args[0])
    except ValueError:
        return _emit_backlog_result(
            {
                "success": False,
                "error": f"Item ID must be integer or YOK-N ref, got '{positional_args[0]}'",
            }
        )

    update_args = positional_args[1:]
    session_id = _resolve_session_id(None)

    if not done_nonce_verified and _update_requests_done(update_args):
        if os.environ.get("YOKE_DONE_RECOVERY") == "1":
            result = _run_done_recovery(item_id)
            return _emit_backlog_result(result, log=str(result.get("log", "") or ""))
        done_nonce_verified, nonce_error = _consume_done_nonce(item_id)
        if not done_nonce_verified:
            return _emit_backlog_result({"success": False, "error": nonce_error})

    captured = io.StringIO()
    result: dict

    if (
        len(update_args) >= 2
        and update_args[0] == "body"
        and update_args[1] in ("--body-file", "--stdin")
    ):
        result = {
            "success": False,
            "error": (
                "raw body writes are no longer supported. "
                "items.body is a rendered projection -- write to a structured field instead."
            ),
        }
    elif (
        len(update_args) >= 2
        and update_args[0] in backlog.VALID_STRUCTURED_FIELDS
        and update_args[1] in ("--body-file", "--stdin")
    ):
        field = update_args[0]
        file_path: Optional[str] = None
        use_stdin = False
        force_flag = False
        source = ""
        j = 1
        while j < len(update_args):
            token = update_args[j]
            if token == "--body-file" and j + 1 < len(update_args):
                file_path = update_args[j + 1]
                j += 2
            elif token == "--stdin":
                use_stdin = True
                j += 1
            elif token == "--force":
                force_flag = True
                j += 1
            elif token == "--source" and j + 1 < len(update_args):
                source = update_args[j + 1]
                j += 2
            else:
                print(f"Unknown argument: {token}", file=sys.stderr)
                return 2

        try:
            content_input = resolve_content_input(
                stdin_flag=use_stdin, body_file=file_path,
            )
        except ContentInputError as exc:
            print(json.dumps({"success": False, "error": exc.message}))
            return exc.exit_code

        # Route the structured-field write through the function
        # dispatcher. The legacy stdout/exit-code contract is preserved for
        # default (non-``--json``) callers by translating the typed envelope
        # back to the legacy result dict. ``--json`` callers receive the
        # FunctionCallResponse envelope verbatim.
        if content_input.mode == "stdin":
            content_str = content_input.content or ""
        else:
            try:
                with open(content_input.file_path or "", "r", encoding="utf-8") as fh:
                    content_str = fh.read()
            except OSError as exc:
                err = {
                    "success": False,
                    "error": f"file not found: {content_input.file_path}",
                }
                if json_mode:
                    print(json.dumps(err))
                    return 1
                print(json.dumps(err))
                return 1

        return _dispatch_structured_field_replace(
            item_id=item_id,
            field=field,
            content=content_str,
            force=force_flag,
            source=source,
            json_mode=json_mode,
            captured=captured,
        )
    elif "=" in update_args[0]:
        updated_count = 0
        for pair in update_args:
            if "=" not in pair:
                print(
                    "Usage: execute-update-cli <item-id> <field=value>...",
                    file=sys.stderr,
                )
                return 2
            field, value = pair.split("=", 1)
            if not field:
                print(f"Invalid field in '{pair}'", file=sys.stderr)
                return 2
            result = backlog.execute_update(
                item_id=item_id,
                field=field,
                value=value,
                done_nonce_verified=done_nonce_verified,
                qa_bypass=qa_bypass,
                session_id=session_id,
                rebuild_board=False,
                out=captured,
            )
            if not result.get("success"):
                result = dict(result)
                result.setdefault("updated_count", updated_count)
                break
            updated_count += 1
        else:
            result = {"success": True, "updated_count": updated_count}
            backlog._maybe_rebuild_board(not no_rebuild, out=captured)
    else:
        if len(update_args) != 2:
            print(
                "Usage: execute-update-cli <item-id> <field> <value>",
                file=sys.stderr,
            )
            return 2
        field, value = update_args
        result = backlog.execute_update(
            item_id=item_id,
            field=field,
            value=value,
            done_nonce_verified=done_nonce_verified,
            qa_bypass=qa_bypass,
            session_id=session_id,
            rebuild_board=not no_rebuild,
            out=captured,
        )

    return _emit_backlog_result(dict(result), log=captured.getvalue())


__all__ = [
    "cmd_execute_update",
    "cmd_execute_update_cli",
]
