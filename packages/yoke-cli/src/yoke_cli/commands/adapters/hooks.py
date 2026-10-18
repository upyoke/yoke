"""Thin entrypoint for the machine-local hook evaluator.

``yoke hook evaluate`` runs on every harness tool call, ahead of the command
registry (see :mod:`yoke_cli.main`), so this module imports only what the
resident round trip needs. Everything the canonical in-process fallback
needs loads inside that fallback.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import os
import sys
import time
from typing import List

from yoke_cli.commands.adapters.hook_config_dedup import (
    is_cursor_config_invocation,
    should_skip_config_duplicate,
)
from yoke_contracts.hook_runner.config_owner import CONFIG_OWNER_ENV_VAR
from yoke_contracts.hook_runner.cursor_response import cursor_allow_stdout


__all__ = ["HOOK_EVALUATE_USAGE", "hook_evaluate"]


HOOK_EVALUATE_USAGE = "yoke hook evaluate <event> [--dry-run]"


def _read_stdin() -> str:
    try:
        return sys.stdin.read()
    except OSError:
        return ""


def _evaluate_inprocess(
    event_name: str,
    stdin_data: str,
    *,
    dry_run: bool,
    cursor_invocation: bool,
    fallback_reason: str = "",
    client_timing=None,
    elapsed_ms: list[int] | None = None,
) -> int:
    """Run the canonical chain here, recording what the evaluation cost.

    The measured span deliberately encloses the completion callback, so any
    synchronous telemetry reporting is charged to the phase that performed
    it rather than vanishing between phases.
    """
    from yoke_cli.commands.adapters.hook_inprocess import evaluate_inprocess
    from yoke_cli.hook_client_wall import record_client_wall
    from yoke_cli.invocation_locality import control_plane_locality

    stdout = io.StringIO()
    stderr = io.StringIO()
    started = time.monotonic()
    with (
        control_plane_locality(None),
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
    ):
        exit_code = evaluate_inprocess(
            event_name,
            stdin_data,
            dry_run=dry_run,
            cursor_invocation=cursor_invocation,
            fallback_reason=fallback_reason,
            client_timing_id=(client_timing.event_id if client_timing else ""),
            on_complete=(
                (
                    lambda: record_client_wall(
                        client_timing.event_id,
                        client_timing.elapsed_ms(),
                    )
                )
                if client_timing is not None
                else None
            ),
        )
    if elapsed_ms is not None:
        elapsed_ms.append(max(0, int((time.monotonic() - started) * 1000)))
    if stdout.getvalue():
        sys.stdout.write(stdout.getvalue())
    if stderr.getvalue():
        sys.stderr.write(stderr.getvalue())
    return exit_code


def hook_evaluate(args: List[str]) -> int:
    from yoke_cli.hook_client_wall import HookClientWall

    client_timing = HookClientWall.start()
    parser = argparse.ArgumentParser(
        formatter_class=argparse.RawDescriptionHelpFormatter,
        prog="yoke hook evaluate",
        description=HOOK_EVALUATE_USAGE,
    )
    parser.add_argument(
        "event_name",
        help="Hook event name (for example PreToolUse, PostToolUse, Stop).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the ordered hook chain and exit.",
    )
    try:
        parsed = parser.parse_args(args)
    except SystemExit as exc:
        if exc.code == 0:
            raise
        print(f"Usage: {HOOK_EVALUATE_USAGE}", file=sys.stderr)
        return 2

    stdin_data = "" if parsed.dry_run else _read_stdin()
    cursor_invocation = is_cursor_config_invocation(os.environ, stdin_data)
    if (
        not parsed.dry_run
        and os.environ.get(CONFIG_OWNER_ENV_VAR)
        and should_skip_config_duplicate(
            parsed.event_name,
            os.environ,
            stdin_data,
        )
    ):
        # Claude and Codex read empty stdout with exit 0 as a no-op allow;
        # Cursor's gated events need an explicit allow reply.
        stdout = cursor_allow_stdout(parsed.event_name) if cursor_invocation else ""
        if stdout:
            sys.stdout.write(stdout)
        return 0

    # Unit tests retain a deterministic in-process seam. Resident behavior is
    # exercised by its own process-level tests with this variable removed.
    if parsed.dry_run or os.environ.get("PYTEST_CURRENT_TEST"):
        return _evaluate_inprocess(
            parsed.event_name,
            stdin_data,
            dry_run=parsed.dry_run,
            cursor_invocation=cursor_invocation,
            client_timing=None if parsed.dry_run else client_timing,
        )

    from yoke_cli.hook_resident_client import (
        ResidentUnavailable,
        evaluate_with_resident,
    )
    from yoke_cli.hook_resident_health import claim_fallback_warning

    try:
        result = evaluate_with_resident(
            parsed.event_name,
            stdin_data,
            client_timing_id=client_timing.event_id,
            client_started_monotonic=client_timing.started_monotonic,
        )
    except ResidentUnavailable as exc:
        if claim_fallback_warning(exc.log_path.parent):
            sys.stderr.write(
                f"WARNING: {exc.code}: {exc.detail}; using canonical in-process "
                f"fallback (resident log: {exc.log_path}; "
                "check: yoke watch doctor -- --only hook-resident)\n"
            )
        fallback_ms: list[int] = []
        exit_code = _evaluate_inprocess(
            parsed.event_name,
            stdin_data,
            dry_run=False,
            cursor_invocation=cursor_invocation,
            fallback_reason=exc.code,
            client_timing=client_timing,
            elapsed_ms=fallback_ms,
        )
        # Keep the phase evidence in diagnostics, outside harness chat.
        _report_phase_timing(
            resident_wait_ms=exc.resident_wait_ms,
            fallback_ms=fallback_ms[0] if fallback_ms else None,
            client_timing=client_timing,
            fallback_reason=exc.code,
            always=True,
        )
        return exit_code

    if result.stdout:
        sys.stdout.write(result.stdout)
    if result.stderr:
        sys.stderr.write(result.stderr)
    _report_phase_timing(
        resident_wait_ms=result.resident_wait_ms,
        fallback_ms=None,
        client_timing=client_timing,
        fallback_reason="",
    )
    return result.exit_code


def _report_phase_timing(
    *,
    resident_wait_ms: int | None,
    fallback_ms: int | None,
    client_timing,
    fallback_reason: str,
    always: bool = False,
) -> None:
    """Log the phase split when it is wanted, and never fail the hook."""
    try:
        from yoke_cli.hook_phase_timing import (
            HookPhaseTiming,
            phase_timing_requested,
            record_phase_timing,
        )

        if not always and not phase_timing_requested():
            return
        timing = HookPhaseTiming(
            resident_wait_ms=resident_wait_ms,
            fallback_ms=fallback_ms,
            client_wall_ms=(
                client_timing.elapsed_ms() if client_timing is not None else None
            ),
            fallback_reason=fallback_reason,
        )
        record_phase_timing(timing)
    except Exception:  # noqa: BLE001 — diagnostics never block a tool call
        return
