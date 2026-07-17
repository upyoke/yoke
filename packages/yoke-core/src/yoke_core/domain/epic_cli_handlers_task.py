"""Handler group: task CRUD, files, history, dispatch-chain.

Owns the following ``python3 -m yoke_core.domain.epic`` subcommands:

- ``task-upsert``, ``task-get``, ``task-list``
- ``task-update-status``, ``task-update-body``, ``task-get-body``,
  ``task-update-field``
- ``file-add``, ``file-list``
- ``history-insert``
- ``dispatch-chain-upsert``, ``dispatch-chain-get``,
  ``dispatch-chain-update``, ``dispatch-chain-list``,
  ``dispatch-chain-advance``

The companion handler group is :mod:`yoke_core.domain.epic_cli_handlers_review`.

The dispatch entry point is :func:`handle`, which the ``epic_cli.main`` loop
calls in a try/except skeleton.  Exceptions raised here propagate to that
caller for unified exit-code mapping (``LookupError``, ``ValueError``,
``PermissionError``, ``IndexError``, ``RuntimeError``).
"""

from __future__ import annotations

import json
import os

from yoke_core.domain.epic_cli import (
    _TASK_UPDATE_BODY_USAGE,
    _cli_error,
    _cli_usage_error,
)


def handle(epic_module, conn, subcmd, rest, epic_id) -> bool:
    """Dispatch task / file / history / dispatch-chain subcommands.

    Returns ``True`` if this handler owned ``subcmd`` (caller stops looking),
    ``False`` to fall through to the next handler group.
    """
    _epic = epic_module

    if subcmd == "task-upsert":
        if not epic_id or len(rest) < 2:
            _cli_usage_error("Usage: task-upsert <epic-id> <task_num> <title> [worktree] [context_estimate] [dependencies]")
        task_num = int(rest[0])
        title = rest[1]
        worktree = rest[2] if len(rest) > 2 else ""
        context_estimate = rest[3] if len(rest) > 3 else ""
        dependencies = rest[4] if len(rest) > 4 else ""
        print(_epic.task_upsert(conn, epic_id, task_num, title, worktree, context_estimate, dependencies))
        return True

    if subcmd == "task-get":
        if not epic_id or len(rest) < 1:
            _cli_usage_error("Usage: task-get <epic-id> <task_num>")
        print(_epic.task_get(conn, epic_id, int(rest[0])))
        return True

    if subcmd == "task-list":
        if not epic_id:
            _cli_usage_error("Usage: task-list <epic-id>")
        result = _epic.task_list(conn, epic_id)
        if result:
            print(result)
        return True

    if subcmd == "task-update-status":
        if not epic_id or len(rest) < 2:
            _cli_usage_error("Usage: task-update-status <epic-id> <task_num> <status>")
        pipeline = os.environ.get("YOKE_STATUS_PIPELINE") == "1"
        force = os.environ.get("YOKE_FORCE") == "1"
        scripts_dir = os.environ.get("YOKE_SCRIPTS_DIR")
        print(_epic.task_update_status(
            conn, epic_id, int(rest[0]), rest[1],
            pipeline=pipeline, force=force,
            scripts_dir=scripts_dir,
        ))
        return True

    if subcmd == "task-update-body":
        if not epic_id or len(rest) < 1:
            _cli_usage_error(_TASK_UPDATE_BODY_USAGE)
        task_num = int(rest[0])
        body_rest = rest[1:]
        json_mode = False
        # ``--json`` may appear anywhere in body_rest; pull it out first so
        # the remaining tokens fall into the legacy positional shape.
        if "--json" in body_rest:
            json_mode = True
            body_rest = [t for t in body_rest if t != "--json"]
        if body_rest and body_rest[0] == "--body-file":
            if len(body_rest) < 2 or not body_rest[1]:
                _cli_usage_error(_TASK_UPDATE_BODY_USAGE)
            with open(body_rest[1], "r") as f:
                body = f.read()
        elif body_rest:
            _cli_usage_error(_TASK_UPDATE_BODY_USAGE)
        else:
            body = _epic._read_stdin_safe()

        # Route epic task body replace through the function
        # dispatcher (``workflow_item.epic_task.body_replace``).
        from yoke_core.domain.epic_cli_dispatch import (
            dispatch_task_update_body,
        )

        rc = dispatch_task_update_body(
            epic_module=_epic,
            conn=conn,
            epic_id=epic_id,
            task_num=task_num,
            body=body,
            json_mode=json_mode,
        )
        if rc != 0:
            _cli_error("task-update-body dispatch failed", rc)
        return True

    if subcmd == "task-get-body":
        if not epic_id or len(rest) < 1:
            _cli_usage_error(
                "Usage: task-get-body <epic-id> <task_num> [--output-file <path>]"
            )
        task_num = int(rest[0])
        # Parse the optional --output-file flag (item-body renderer convention,
        # see render_body.render_item) and reject any other trailing token. A
        # mistyped or unsupported flag must fail loudly here: silently
        # discarding it printed the body to stdout while the expected file was
        # never created, so a chained read of that path failed misleadingly.
        output_file = None
        extra = rest[1:]
        i = 0
        while i < len(extra):
            token = extra[i]
            if token == "--output-file":
                if i + 1 >= len(extra) or not extra[i + 1]:
                    _cli_usage_error("Error: --output-file requires a path argument")
                output_file = extra[i + 1]
                i += 2
                continue
            _cli_usage_error(f"Error: unknown argument '{token}'")
        result = _epic.task_get_body(conn, epic_id, task_num)
        if output_file is not None:
            from pathlib import Path
            Path(output_file).write_text(result, encoding="utf-8")
        else:
            print(result)
        return True

    if subcmd == "task-update-field":
        if not epic_id or len(rest) < 2:
            _cli_usage_error("Usage: task-update-field <epic-id> <task_num> <field> <value>")
        value = rest[2] if len(rest) > 2 else ""
        pipeline = os.environ.get("YOKE_STATUS_PIPELINE") == "1"
        force = os.environ.get("YOKE_FORCE") == "1"
        print(
            _epic.task_update_field(
                conn,
                epic_id,
                int(rest[0]),
                rest[1],
                value,
                pipeline=pipeline,
                force=force,
            )
        )
        return True

    if subcmd == "file-add":
        if not epic_id or len(rest) < 2:
            _cli_usage_error("Usage: file-add <epic-id> <task_num> <file_path> <action>")
        action = rest[2] if len(rest) > 2 else ""
        print(_epic.file_add(conn, epic_id, int(rest[0]), rest[1], action))
        return True

    if subcmd == "file-list":
        if not epic_id or len(rest) < 1:
            _cli_usage_error("Usage: file-list <epic-id> <task_num>")
        result = _epic.file_list(conn, epic_id, int(rest[0]))
        if result:
            print(result)
        return True

    if subcmd == "history-insert":
        if not epic_id or len(rest) < 3:
            _cli_usage_error("Usage: history-insert <epic-id> <task_num> <from_status> <to_status> [note | --body-file <path>]")
        body_args = rest[3:]
        if body_args and body_args[0] == "--body-file":
            if len(body_args) < 2 or not body_args[1]:
                _cli_usage_error("Usage: history-insert <epic-id> <task_num> <from_status> <to_status> [note | --body-file <path>]")
            try:
                with open(body_args[1], "r", encoding="utf-8") as fh:
                    note = fh.read()
            except OSError as exc:
                _cli_error(f"--body-file path unreadable: {body_args[1]}: {exc}")
        else:
            note = body_args[0] if body_args else ""
        print(_epic.history_insert(conn, epic_id, int(rest[0]), rest[1], rest[2], note))
        return True

    if subcmd == "dispatch-chain-upsert":
        if not epic_id or len(rest) < 1:
            _cli_usage_error("Usage: dispatch-chain-upsert <epic-id> <worktree> (reads JSON from stdin)")
        raw_json = _epic._read_stdin_safe()
        try:
            data = json.loads(raw_json) if raw_json.strip() else {}
        except json.JSONDecodeError as e:
            _cli_error(f"invalid JSON: {e}")
        print(_epic.dispatch_chain_upsert(conn, epic_id, rest[0], data))
        return True

    if subcmd == "dispatch-chain-get":
        if not epic_id or len(rest) < 1:
            _cli_usage_error("Usage: dispatch-chain-get <epic-id> <worktree>")
        print(_epic.dispatch_chain_get(conn, epic_id, rest[0]))
        return True

    if subcmd == "dispatch-chain-update":
        if not epic_id or len(rest) < 2:
            _cli_usage_error("Usage: dispatch-chain-update <epic-id> <worktree> <field> <value>")
        value = rest[2] if len(rest) > 2 else ""
        print(_epic.dispatch_chain_update(conn, epic_id, rest[0], rest[1], value))
        return True

    if subcmd == "dispatch-chain-list":
        if not epic_id:
            _cli_usage_error("Usage: dispatch-chain-list <epic-id>")
        result = _epic.dispatch_chain_list(conn, epic_id)
        if result:
            print(result)
        return True

    if subcmd == "dispatch-chain-advance":
        if not epic_id or len(rest) < 1:
            _cli_usage_error("Usage: dispatch-chain-advance <epic-id> <worktree>")
        print(_epic.dispatch_chain_advance(conn, epic_id, rest[0]))
        return True

    if subcmd == "dispatch-chain-refresh-activation":
        if not epic_id or len(rest) < 2:
            _cli_usage_error(
                "Usage: dispatch-chain-refresh-activation "
                "<epic-id> <worktree> <task-num>"
            )
        print(
            _epic.dispatch_chain_refresh_for_activation(
                conn, epic_id, rest[0], rest[1]
            )
        )
        return True

    return False
