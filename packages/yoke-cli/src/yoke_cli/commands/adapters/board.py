"""``yoke board rebuild`` flag adapter.

The rebuild + render paths run on the client-tier :mod:`yoke_cli.board`
modules, so ``yoke board rebuild`` works end-to-end without loading engine
code. The source-dev timing telemetry (``board_rebuild_timing_events`` +
``events_writes``, both DB-backed) is soft-gated: when the ``yoke_core``
timing surface is importable the command emits the same
Started/Completed/Failed events as before; otherwise the timing surface
degrades to no-ops and the rebuild still runs.
"""

from __future__ import annotations

import argparse
import importlib
import sys
from contextlib import contextmanager
from typing import Dict, List, Tuple

from yoke_cli.commands.git_hook import AdapterFn
from yoke_cli.board import rebuild as board_rebuild_flow
from yoke_cli.board.outcome import printed as _printed_outcome
from yoke_cli.config import machine_config
from yoke_cli.commands.board_rebuild_output import (
    board_payload,
    coerce_rebuild_outcome,
    emit_board_human,
    emit_board_json,
    emit_board_print,
    read_board_text,
    result_board_path,
)
from yoke_cli.commands.board_terminal_output import format_data_source
from yoke_cli.commands._helpers import (
    add_json_arg,
    add_session_arg,
    parse_or_usage_error,
    usage_error,
)
from yoke_contracts.board.phase_timer import PhaseRecorder


BOARD_REBUILD_USAGE = (
    "yoke board rebuild [--force] [--repo-root PATH] [--output-name NAME] "
    "[--scope NAME] [--print | --print-only] [--no-pager] [--session-id S] [--json]"
)


def _print_mode(parsed: argparse.Namespace) -> str:
    if parsed.print_only:
        return "print_only"
    if parsed.print_board:
        return "print"
    return ""


class _NullTiming:
    """No-op timing surface used when the engine timing module cannot load.

    Mirrors the ``board_rebuild_timing_events`` call surface the adapter uses so
    the command can emit nothing without branching on core-availability at every
    call site.
    """

    @staticmethod
    def ambient_session_id(explicit):
        import os

        if explicit:
            return explicit
        for env_name in ("YOKE_SESSION_ID", "CLAUDE_SESSION_ID", "CODEX_THREAD_ID"):
            value = os.environ.get(env_name)
            if value:
                return value
        return ""

    @staticmethod
    def new_trace_id():
        import uuid

        return str(uuid.uuid4())

    @staticmethod
    def utc_now():
        from datetime import datetime, timezone

        return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
            "+00:00", "Z"
        )

    @staticmethod
    def start_clock():
        import time

        return time.perf_counter()

    @staticmethod
    def duration_ms(start):
        import time

        return max(0, int((time.perf_counter() - start) * 1000))

    @staticmethod
    def emit_board_command_event(*_args, **_kwargs):
        return None


@contextmanager
def _timing_connection():
    """Yield ``(timing, conn)``: the core timing module + an emit connection.

    The timing telemetry is DB-backed source-dev surface; the literal
    ``importlib.import_module(...)`` form lets the installer package-boundary test
    classify the edge while keeping it optional. When the engine import is
    unavailable both degrade to no-ops — the timing shim swallows every event,
    the connection is ``None``.
    """
    try:
        timing = importlib.import_module(
            "yoke_core.cli.board_rebuild_timing_events"
        )
        events_writes = importlib.import_module("yoke_core.domain.events_writes")
    except ImportError:
        yield _NullTiming(), None
        return
    with events_writes.hook_emit_connection() as event_conn:
        yield timing, event_conn


def board_rebuild(args: List[str]) -> int:
    parser = argparse.ArgumentParser(
        prog="yoke board rebuild", description=BOARD_REBUILD_USAGE,
    )
    parser.add_argument("--force", action="store_true",
                        help="Force a rebuild even if no changes detected.")
    parser.add_argument("--repo-root", dest="repo_root", default=None,
                        help="Repository root whose board should be rebuilt.")
    parser.add_argument("--output-name", dest="output_name", default=None,
                        help="Override default BOARD.md output filename.")
    parser.add_argument("--scope", default=None,
                        help="Optional rebuild scope filter.")
    parser.add_argument("--print", dest="print_board", action="store_true",
                        help="Print the board after rebuilding it.")
    parser.add_argument("--print-only", dest="print_only", action="store_true",
                        help="Print the rendered board without writing files.")
    parser.add_argument("--no-pager", dest="no_pager", action="store_true",
                        help="Disable paging; write the board straight to stdout "
                             "(paging otherwise activates on an interactive TTY).")
    add_session_arg(parser); add_json_arg(parser)
    parsed = parse_or_usage_error(parser, args, BOARD_REBUILD_USAGE)
    if parsed is None:
        return 2
    if parsed.print_board and parsed.print_only:
        return usage_error("--print and --print-only are mutually exclusive")
    if parsed.json_mode and (parsed.print_board or parsed.print_only):
        return usage_error("--json cannot be combined with board print modes")

    try:
        repo_root = board_rebuild_flow.resolve_main_repo_root(parsed.repo_root)
    except board_rebuild_flow.BoardProjectResolutionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    board_path = board_rebuild_flow.resolve_board_path(repo_root, parsed.output_name)
    effective_scope = parsed.scope or machine_config.board_scope(repo_root)
    force = bool(parsed.force)
    print_mode = _print_mode(parsed)
    phase_recorder = PhaseRecorder()
    event_ids: list[str] = []
    board_text: str | None = None

    with _timing_connection() as (timing, event_conn):
        session_id = timing.ambient_session_id(parsed.session_id)
        trace_id = timing.new_trace_id()
        started_at = timing.utc_now()
        started_perf = timing.start_clock()
        start_event_id = timing.emit_board_command_event(
            "BoardRebuildCommandStarted",
            repo_root=repo_root,
            board_path=board_path,
            force=force,
            output_name=parsed.output_name,
            scope=parsed.scope,
            print_mode=print_mode,
            session_id=session_id,
            trace_id=trace_id,
            started_at=started_at,
            conn=event_conn,
        )
        if start_event_id:
            event_ids.append(start_event_id)

        try:
            if parsed.print_only:
                repo_root, board_path, board_text = board_rebuild_flow.render_text(
                    repo_arg=str(repo_root),
                    output_name=parsed.output_name,
                    scope=effective_scope,
                    phase_recorder=phase_recorder,
                )
                result = _printed_outcome(board_path)
            else:
                raw_result = board_rebuild_flow.rebuild(
                    repo_arg=str(repo_root),
                    force=force,
                    output_name=parsed.output_name,
                    scope=effective_scope,
                    emit=False,
                    phase_recorder=phase_recorder,
                )
                result = coerce_rebuild_outcome(raw_result)
                if parsed.print_board and result.exit_code == 0:
                    board_text = read_board_text(
                        result, repo_root=repo_root,
                        output_name=parsed.output_name,
                    )
        except Exception as exc:
            duration = timing.duration_ms(started_perf)
            completed_at = timing.utc_now()
            failure_event_id = timing.emit_board_command_event(
                "BoardRebuildCommandFailed",
                repo_root=repo_root,
                board_path=board_path,
                force=force,
                output_name=parsed.output_name,
                scope=parsed.scope,
                print_mode=print_mode,
                session_id=session_id,
                trace_id=trace_id,
                started_at=started_at,
                completed_at=completed_at,
                duration_ms_value=duration,
                exit_code=1,
                status="exception",
                message=str(exc),
                exception_type=type(exc).__name__,
                phases_ms=phase_recorder.snapshot(),
                conn=event_conn,
            )
            if failure_event_id:
                event_ids.append(failure_event_id)
            raise

        payload = board_payload(
            result,
            repo_root=repo_root,
            output_name=parsed.output_name,
            content=board_text if board_text is not None else None,
            scope=effective_scope,
            env_name=_active_env_name(),
            data_source=_active_data_source(),
        )
        duration = timing.duration_ms(started_perf)
        completed_at = timing.utc_now()
        payload.update({
            "started_at": started_at,
            "completed_at": completed_at,
            "duration_ms": duration,
            "trace_id": trace_id,
            "phases_ms": phase_recorder.snapshot(),
            "print_mode": print_mode,
        })
        finished_event_id = timing.emit_board_command_event(
            (
                "BoardRebuildCommandCompleted"
                if result.exit_code == 0
                else "BoardRebuildCommandFailed"
            ),
            repo_root=repo_root,
            board_path=result_board_path(result, repo_root, parsed.output_name),
            force=force,
            output_name=parsed.output_name,
            scope=parsed.scope,
            print_mode=print_mode,
            session_id=session_id,
            trace_id=trace_id,
            started_at=started_at,
            completed_at=completed_at,
            duration_ms_value=duration,
            exit_code=int(result.exit_code),
            status=result.status,
            changed=result.changed,
            message=result.message,
            targets=payload["targets"],
            phases_ms=phase_recorder.snapshot(),
            conn=event_conn,
        )
        if finished_event_id:
            event_ids.append(finished_event_id)
    if parsed.json_mode:
        emit_board_json(result, payload, event_ids=event_ids)
    elif parsed.print_board or parsed.print_only:
        emit_board_print(result, payload, board_text or "", no_pager=parsed.no_pager)
    else:
        emit_board_human(result, payload)
    return int(result.exit_code)


def _active_env_name() -> str:
    try:
        return machine_config.active_env()
    except Exception:
        return ""


def _active_data_source() -> str:
    try:
        return format_data_source(machine_config.active_connection())
    except Exception:
        return ""


def board(args: List[str]) -> int:
    """``yoke board`` — shortcut for ``yoke board rebuild --print``.

    Bare ``yoke board`` rebuilds and prints the board; passing an explicit
    print/json mode (or other rebuild flags) is forwarded unchanged so the
    shortcut never fights a caller who already chose an output mode.
    """
    output_modes = ("--print", "--print-only", "--json")
    if any(arg in output_modes for arg in args):
        return board_rebuild(list(args))
    return board_rebuild(["--print", *args])


# `yoke board` carries no distinct function id (it is sugar over
# board.rebuild.run), so it registers as a tool-shaped shortcut.
TOOL_SHAPED_SUBCOMMANDS: Dict[Tuple[str, ...], AdapterFn] = {
    ("board",): board,
}

TOOL_SHAPED_USAGE: Dict[str, str] = {
    "yoke board": (
        "Rebuild and print the project status board "
        "(shortcut for `board rebuild --print`)."
    ),
}


__all__ = [
    "BOARD_REBUILD_USAGE",
    "TOOL_SHAPED_SUBCOMMANDS",
    "TOOL_SHAPED_USAGE",
    "board",
    "board_rebuild",
]
