#!/usr/bin/env python3
# Template authority: Yoke templates/webapp/ops/docker_maintenance_converge.py.
"""Converge safe Docker maintenance in the current user's crontab.

This replaces Yoke's exact historical ``docker image prune`` cron shape with
one marked, canonical dangling-only weekly job. Operator-authored image jobs
and all other crontab content are preserved. The operation is idempotent,
verifies the installed result, retries transient write failures, and exits
nonzero when convergence cannot be proven.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path

DEFAULT_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 2.0
YOKE_MAINTENANCE_MARKER = "# yoke:docker-maintenance"
WEEKLY_SCHEDULE = "30 4 * * 0"
_LEGACY_YOKE_ENTRY = re.compile(
    r"^30[ \t]+4[ \t]+\*[ \t]+\*[ \t]+0[ \t]+"
    r"\([ \t]*docker[ \t]+builder[ \t]+prune[ \t]+-af[ \t]+&&[ \t]+"
    r"docker[ \t]+image[ \t]+prune[ \t]+-(?:af|f)[ \t]*\)[ \t]+"
    r">>[ \t]+\S*docker-prune\.log[ \t]+2>&1[ \t]*$"
)

CommandResult = subprocess.CompletedProcess[str]
CommandRunner = Callable[[Sequence[str], str | None], CommandResult]


class MaintenanceConvergenceError(RuntimeError):
    """Safe Docker maintenance could not be proven installed."""


def _run(arguments: Sequence[str], input_text: str | None = None) -> CommandResult:
    try:
        return subprocess.run(
            list(arguments),
            capture_output=True,
            check=False,
            input=input_text,
            text=True,
        )
    except OSError as exc:
        raise MaintenanceConvergenceError(
            f"could not execute {arguments[0]}: {exc.__class__.__name__}"
        ) from exc


def canonical_weekly_entry(home: Path) -> str:
    log_path = home / "docker-prune.log"
    return (
        f"{WEEKLY_SCHEDULE} (docker builder prune -af && "
        f"docker image prune -f) >> {log_path} 2>&1 "
        f"{YOKE_MAINTENANCE_MARKER}"
    )


def _is_image_prune_entry(line: str) -> bool:
    stripped = line.lstrip()
    if not stripped or stripped.startswith("#"):
        return False
    if stripped.endswith(YOKE_MAINTENANCE_MARKER):
        return True
    return _LEGACY_YOKE_ENTRY.fullmatch(stripped) is not None


def reconcile_crontab(current: str, canonical: str | None) -> tuple[str, bool]:
    """Return deterministic crontab text and whether a write is required."""
    original = current if not current or current.endswith("\n") else current + "\n"
    lines = current.splitlines()
    matches = [line for line in lines if _is_image_prune_entry(line)]
    if canonical is not None and matches == [canonical]:
        return original, False
    if canonical is None and not matches:
        return original, False

    retained = [line for line in lines if not _is_image_prune_entry(line)]
    while retained and not retained[-1].strip():
        retained.pop()
    if canonical is not None:
        retained.append(canonical)
    desired = "\n".join(retained)
    if desired:
        desired += "\n"
    return desired, desired != original


def _detail(result: CommandResult) -> str:
    return (result.stderr or result.stdout or f"rc={result.returncode}").strip()[-500:]


def _read_crontab(runner: CommandRunner) -> str:
    result = runner(["crontab", "-l"], None)
    if result.returncode == 0:
        return result.stdout
    detail = _detail(result)
    if result.returncode == 1 and "no crontab for" in detail.lower():
        return ""
    raise MaintenanceConvergenceError(f"could not read crontab: {detail}")


def converge_maintenance(
    *,
    home: Path | None = None,
    remove_only: bool = False,
    attempts: int = DEFAULT_ATTEMPTS,
    runner: CommandRunner = _run,
    pause: Callable[[float], None] = time.sleep,
    emit: Callable[[str], None] = print,
) -> bool:
    """Install the canonical weekly entry; return whether state changed."""
    if attempts < 1:
        raise MaintenanceConvergenceError("attempts must be at least 1")
    canonical = None if remove_only else canonical_weekly_entry(home or Path.home())
    desired, changed = reconcile_crontab(_read_crontab(runner), canonical)
    if not changed:
        state = "absent" if remove_only else "already canonical"
        emit(f"docker maintenance: weekly image cleanup {state}")
        return False

    last_failure = "unknown crontab failure"
    for attempt in range(1, attempts + 1):
        result = runner(["crontab", "-"], desired)
        if result.returncode == 0:
            _verified, drifted = reconcile_crontab(_read_crontab(runner), canonical)
            if not drifted:
                action = "removed" if remove_only else "converged"
                emit(f"docker maintenance: safe weekly image cleanup {action}")
                return True
            last_failure = "post-write verification still found cron drift"
        else:
            last_failure = _detail(result)
        if attempt < attempts:
            emit(f"docker maintenance: attempt {attempt}/{attempts} failed; retrying")
            pause(RETRY_DELAY_SECONDS)

    raise MaintenanceConvergenceError(
        f"could not converge safe weekly image cleanup after {attempts} attempts: "
        f"{last_failure}"
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--attempts", type=int, default=DEFAULT_ATTEMPTS)
    parser.add_argument("--remove-only", action="store_true")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        converge_maintenance(
            attempts=args.attempts,
            remove_only=args.remove_only,
        )
    except MaintenanceConvergenceError as exc:
        print(f"docker maintenance convergence failed: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
