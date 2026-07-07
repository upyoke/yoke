"""Handler group: review, progress notes, simulation, triage handoff, cascade.

Owns the following ``python3 -m yoke_core.domain.epic`` subcommands:

- ``review-seed``, ``review-insert``, ``review-get``
- ``progress-note-insert``, ``progress-note-list-unsynced``,
  ``progress-note-mark-synced``
- ``simulation-upsert``, ``simulation-get``
- ``proceed-triage-handoff``
- ``cascade-task-status``
- ``orphan-check``, ``migrate-task-files``

The companion handler group is :mod:`yoke_core.domain.epic_cli_handlers_task`.

The dispatch entry point is :func:`handle`, which the ``epic_cli.main`` loop
calls after the task handler returns ``False``.  Exceptions raised here
propagate to that caller for unified exit-code mapping.
"""

from __future__ import annotations

import subprocess
import sys
from typing import Any, List, Optional, Sequence

from yoke_core.domain.epic_cli import _cli_error, _cli_usage_error


def _load_body_arg(body_args: Sequence[str], epic_module: Any, usage: str) -> str:
    """Resolve ``[--body-file <path>]`` against optional positional body args.

    Returns the body string. Reads from ``--body-file <path>`` when present
    (rejects the flag with no path), falls back to ``epic_module._read_stdin_safe()``
    when absent. Surfaces a clear error if the named file is unreadable so
    no partial review/history row lands.
    """
    if body_args and body_args[0] == "--body-file":
        if len(body_args) < 2 or not body_args[1]:
            _cli_usage_error(f"Usage: {usage}")
        path = body_args[1]
        try:
            with open(path, "r", encoding="utf-8") as fh:
                return fh.read()
        except OSError as exc:
            _cli_error(f"--body-file path unreadable: {path}: {exc}")
    return epic_module._read_stdin_safe()


def handle(epic_module, conn, subcmd, rest, epic_id) -> bool:
    """Dispatch review / progress / simulation / triage / cascade subcommands.

    Returns ``True`` if this handler owned ``subcmd`` (caller stops looking),
    ``False`` to fall through (caller should usage-error).
    """
    _epic = epic_module

    if subcmd == "review-seed":
        if not epic_id or len(rest) < 1:
            _cli_usage_error("Usage: review-seed <epic-id> <task_num>")
        try:
            print(_epic.review_seed(conn, epic_id, int(rest[0])))
        except RuntimeError as exc:
            _cli_error(str(exc))
        return True

    if subcmd == "review-insert":
        if not epic_id or len(rest) < 2:
            _cli_usage_error("Usage: review-insert <epic-id> <task_num> <verdict> [--body-file <path>]")
        body = _load_body_arg(rest[2:], _epic, "review-insert <epic-id> <task_num> <verdict> [--body-file <path>]")
        try:
            print(_epic.review_insert(conn, epic_id, int(rest[0]), rest[1], body))
        except RuntimeError as exc:
            _cli_error(str(exc))
        return True

    if subcmd == "review-get":
        if not epic_id or len(rest) < 1:
            _cli_usage_error("Usage: review-get <epic-id> <task_num>")
        print(_epic.review_get(conn, epic_id, int(rest[0])))
        return True

    if subcmd == "progress-note-insert":
        if not epic_id or len(rest) < 2:
            _cli_usage_error("Usage: progress-note-insert <epic-id> <task_num> <note_num> [--body-file <path>]")
        task_num_val = int(rest[0])
        note_num_val = int(rest[1])
        body_rest = rest[2:]
        if body_rest and body_rest[0] == "--body-file":
            if len(body_rest) < 2 or not body_rest[1]:
                _cli_usage_error("Usage: progress-note-insert <epic-id> <task_num> <note_num> [--body-file <path>]")
            with open(body_rest[1], "r") as f:
                body = f.read()
        else:
            body = _epic._read_stdin_safe()
        commit_hash = ""
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--short", "HEAD"],
                capture_output=True, text=True, timeout=5,
            )
            if proc.returncode == 0:
                commit_hash = proc.stdout.strip()
        except (subprocess.TimeoutExpired, FileNotFoundError):
            pass
        print(_epic.progress_note_insert(conn, epic_id, task_num_val, note_num_val, body, commit_hash))
        return True

    if subcmd == "progress-note-list-unsynced":
        if not epic_id:
            _cli_usage_error("Usage: progress-note-list-unsynced <epic-id>")
        result = _epic.progress_note_list_unsynced(conn, epic_id)
        if result:
            print(result)
        return True

    if subcmd == "progress-note-list":
        usage = (
            "Usage: progress-note-list <epic-id> <task-num> [--limit N]\n"
            "   or: progress-note-list <epic-id> --task <task-num> [--limit N]"
        )
        if not epic_id or len(rest) < 1:
            _cli_usage_error(usage)
        # Accept both shapes: positional ``<task-num>`` or ``--task <num>``.
        # Operators frequently reach for the flag form first; rejecting it
        # with the generic top-level help (which is what int() ValueError
        # used to surface) is unnecessary friction.
        task_num_val = None
        limit_val = 0
        i = 0
        while i < len(rest):
            tok = rest[i]
            if tok in ("--task", "--task-num"):
                if i + 1 >= len(rest):
                    _cli_usage_error(usage)
                try:
                    task_num_val = int(rest[i + 1])
                except ValueError:
                    _cli_usage_error(usage)
                i += 2
                continue
            if tok == "--limit":
                if i + 1 >= len(rest):
                    _cli_usage_error(usage)
                try:
                    limit_val = int(rest[i + 1])
                except ValueError:
                    _cli_usage_error(usage)
                i += 2
                continue
            # First non-flag positional is the task num.
            if task_num_val is None and not tok.startswith("-"):
                try:
                    task_num_val = int(tok)
                except ValueError:
                    _cli_usage_error(usage)
                i += 1
                continue
            _cli_usage_error(usage)
        if task_num_val is None:
            _cli_usage_error(usage)
        result = _epic.progress_note_list(
            conn, epic_id, task_num_val, limit_val,
        )
        if result:
            print(result)
        return True

    if subcmd == "progress-note-mark-synced":
        if not epic_id or len(rest) < 2:
            _cli_usage_error("Usage: progress-note-mark-synced <epic-id> <task_num> <note_num>")
        print(_epic.progress_note_mark_synced(conn, epic_id, int(rest[0]), int(rest[1])))
        return True

    if subcmd == "submission-receipt-get":
        if not epic_id or len(rest) < 1:
            _cli_usage_error("Usage: submission-receipt-get <epic-id> <task_num> [--after-note-count N]")
        task_num_val = int(rest[0])
        after_note_count = 0
        receipt_rest = rest[1:]
        if receipt_rest:
            if len(receipt_rest) == 2 and receipt_rest[0] == "--after-note-count":
                after_note_count = int(receipt_rest[1])
            else:
                _cli_usage_error("Usage: submission-receipt-get <epic-id> <task_num> [--after-note-count N]")
        print(_epic.submission_receipt_get(
            conn,
            epic_id,
            task_num_val,
            after_note_count=after_note_count,
        ))
        return True

    if subcmd == "simulation-upsert":
        if not epic_id or len(rest) < 1:
            _cli_usage_error("Usage: simulation-upsert <epic-id> <phase> (reads body from stdin)")
        body = _epic._read_stdin_safe()
        print(_epic.simulation_upsert(conn, epic_id, rest[0], body))
        return True

    if subcmd == "simulation-get":
        if not epic_id or len(rest) < 1:
            _cli_usage_error("Usage: simulation-get <epic-id> <phase>")
        print(_epic.simulation_get(conn, epic_id, rest[0]))
        return True

    if subcmd == "proceed-triage-handoff":
        if not epic_id:
            _cli_usage_error(
                "Usage: proceed-triage-handoff <epic-id> "
                "[--recommendation R] [--gap-summary S] "
                "[--filed-tickets T1,T2] [--session-id SID]"
            )
        # Parse keyword args from rest
        _pth_recommendation = "PROCEED"
        _pth_gap_summary = ""
        _pth_filed_tickets: Optional[List[str]] = None
        _pth_session_id: Optional[str] = None
        _pth_i = 0
        while _pth_i < len(rest):
            if rest[_pth_i] == "--recommendation" and _pth_i + 1 < len(rest):
                _pth_recommendation = rest[_pth_i + 1]
                _pth_i += 2
            elif rest[_pth_i] == "--gap-summary" and _pth_i + 1 < len(rest):
                _pth_gap_summary = rest[_pth_i + 1]
                _pth_i += 2
            elif rest[_pth_i] == "--filed-tickets" and _pth_i + 1 < len(rest):
                _pth_filed_tickets = [t.strip() for t in rest[_pth_i + 1].split(",") if t.strip()]
                _pth_i += 2
            elif rest[_pth_i] == "--session-id" and _pth_i + 1 < len(rest):
                _pth_session_id = rest[_pth_i + 1]
                _pth_i += 2
            else:
                _pth_i += 1
        conn.close()  # release before calling helper that opens its own conn
        rc = _epic.proceed_triage_and_handoff(
            int(epic_id),
            recommendation=_pth_recommendation,
            gap_summary=_pth_gap_summary,
            filed_ticket_ids=_pth_filed_tickets,
            session_id=_pth_session_id,
        )
        sys.exit(rc)

    if subcmd == "cascade-task-status":
        if not epic_id or len(rest) < 2:
            _cli_usage_error("Usage: cascade-task-status <epic-id> <from-parent-status> <to-parent-status>")
        print(_epic.cascade_task_status(conn, epic_id, rest[0], rest[1]))
        return True

    if subcmd == "orphan-check":
        result = _epic.orphan_check(conn)
        if result:
            print(result)
        return True

    if subcmd == "migrate-task-files":
        print(_epic.migrate_task_files(conn))
        return True

    return False
