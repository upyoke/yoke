"""CLI: ``python3 -m yoke_core.hooks <event> [--dry-run]``.

Resolves the harness via :func:`yoke_core.hooks.helpers_identity.detect_executor`,
loads the per-harness ``AdapterCapability`` lazily via
:mod:`yoke_core.hooks.capability_resolve`, and dispatches to
:func:`run_event`. ``--dry-run`` uses the real capability when available so
subprocess carve-outs are visible in the printed chain.
"""

from __future__ import annotations

import argparse
import json
import sys

from yoke_contracts.hook_runner.failures import render_failure_warning
from yoke_core.hooks.helpers_identity import detect_executor
from yoke_core.hooks.capability_resolve import resolve_capability
from yoke_core.hooks.remote_policy import RunControls
from yoke_core.hooks.runner import run_event
from yoke_harness.hooks.decision_render import write_hook_output


def _client_facts(event_name: str, stdin_data: str, executor: str) -> dict:
    """Collect the client facts every other evaluation path collects too."""
    from yoke_contracts.hook_runner.project_scope import resolve_hook_project_scope
    from yoke_harness.hooks.client_facts import collect_client_facts, event_chain

    try:
        payload = json.loads(stdin_data) if stdin_data else {}
    except json.JSONDecodeError:
        return {}
    if not isinstance(payload, dict):
        return {}
    try:
        chain = event_chain(event_name, payload, resolve_hook_project_scope(payload))
    except (ValueError, OSError, RuntimeError):
        return {}  # run_event refuses the unresolvable scope by name
    return collect_client_facts(event_name, payload, executor, chain)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python3 -m yoke_core.hooks",
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
    executor = detect_executor()
    capability = resolve_capability(executor, args.dry_run)
    controls = RunControls(
        payload_extra={}
        if args.dry_run
        else _client_facts(args.event_name, stdin_data, executor)
    )
    stdout_text, exit_code = run_event(
        args.event_name,
        capability=capability,
        stdin_data=stdin_data,
        dry_run=args.dry_run,
        controls=controls,
    )
    failure_warning = render_failure_warning(controls.degraded)
    if failure_warning:
        sys.stderr.write(failure_warning)
    write_hook_output(stdout_text, exit_code, executor, event_name=args.event_name)
    return exit_code


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
