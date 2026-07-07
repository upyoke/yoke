"""CLI: ``python3 -m runtime.harness.hook_runner <event> [--dry-run]``.

Resolves the harness via :func:`runtime.harness.hook_helpers_identity.detect_executor`,
loads the per-harness ``AdapterCapability`` lazily via
:mod:`runtime.harness.hook_runner.capability_resolve`, and dispatches to
:func:`run_event`. ``--dry-run`` uses the real capability when available so
subprocess carve-outs are visible in the printed chain.
"""

from __future__ import annotations

import argparse
import sys

from runtime.harness.hook_helpers_identity import detect_executor
from runtime.harness.hook_runner.capability_resolve import resolve_capability
from runtime.harness.hook_runner.runner import run_event


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m runtime.harness.hook_runner",
        description="Shared hook-runner dispatch CLI.",
    )
    parser.add_argument("event_name", help="Hook event name (e.g. PreToolUse).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print the ordered chain ([typed]/[subproc] prefixed) and exit.",
    )
    args = parser.parse_args(argv)

    stdin_data = "" if args.dry_run else sys.stdin.read()
    capability = resolve_capability(detect_executor(), args.dry_run)
    stdout_text, exit_code = run_event(
        args.event_name,
        capability=capability,
        stdin_data=stdin_data,
        dry_run=args.dry_run,
    )
    if stdout_text:
        sys.stdout.write(stdout_text)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
