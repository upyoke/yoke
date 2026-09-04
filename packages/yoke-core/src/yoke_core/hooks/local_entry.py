"""Installed local-universe hook evaluation entrypoint.

The CLI imports this module only after it has selected a non-production
local-postgres connection.  At that point the installed core is the control
plane, so the complete registered hook chain runs in-process from the wheel.
"""

from __future__ import annotations

import os
import sys
from typing import Optional

from yoke_contracts.hook_runner.failures import render_failure_warning
from yoke_core.hooks.capability_resolve import resolve_capability
from yoke_core.hooks.remote_policy import RunControls
from yoke_core.hooks.runner import run_event
from yoke_core.hooks.session_model_attestation_write import confirmed_served_model
from yoke_harness.hooks.cursor_lifecycle_hooks import (
    ensure_user_lifecycle_hooks_for_executor,
)
from yoke_contracts.executor_labels import canonical_harness_id
from yoke_harness.hooks.decision_render import merge_allow_stdout
from yoke_harness.hooks.identity import detect_executor, is_cursor
from yoke_harness.hooks.identity_relay import (
    record_model_facts_shipped,
    relay_identity_payload,
)
from yoke_harness.hooks.identity_stamp import record_then_stamp
from yoke_harness.hooks.relay import AGENT_TYPE_ENV_VAR
from yoke_harness.hooks.relay_identity_guard import (
    capture_codex_session,
    parse_hook_payload,
    print_execution_provenance,
    record_client_anchor,
)


def evaluate_local_hook(
    event_name: str,
    stdin_data: str,
    *,
    extra_context: Optional[str] = None,
) -> int:
    """Run one installed hook against the active local universe."""
    payload = parse_hook_payload(stdin_data)
    record_client_anchor(payload, session_start=event_name == "SessionStart")
    executor = detect_executor()
    original_stdin = stdin_data
    stdin_data = record_then_stamp(payload, stdin_data, executor, event_name)
    ensure_user_lifecycle_hooks_for_executor(executor)
    capture_codex_session(event_name, original_stdin, executor)

    identity = relay_identity_payload(event_name, payload, executor)
    payload_extra = {key: value for key, value in identity.items() if value is not None}
    agent_type = os.environ.get(AGENT_TYPE_ENV_VAR, "").strip()
    if agent_type:
        payload_extra["agent_type"] = agent_type
    if extra_context:
        from yoke_core.domain.session_orientation import (
            CLIENT_ORIENTATION_PRESENT_KEY,
        )

        payload_extra[CLIENT_ORIENTATION_PRESENT_KEY] = True
    controls = RunControls(payload_extra=payload_extra)
    stdout, exit_code = run_event(
        event_name,
        capability=resolve_capability(executor),
        stdin_data=stdin_data,
        controls=controls,
    )

    # Even in-process evaluation settles only from the row's write receipt.
    if not controls.timed_out:
        record_model_facts_shipped(
            payload,
            confirmed_served_model(payload.get("session_id"), identity.get("model")),
        )

    failure_warning = render_failure_warning(controls.degraded)
    if failure_warning:
        sys.stderr.write(failure_warning)
        print_execution_provenance()
    elif controls.final_outcome == "deny":
        print_execution_provenance()
    if controls.final_outcome != "deny" and extra_context:
        cursor = is_cursor(executor)
        rendered = _context_stdout(
            extra_context,
            event_name,
            cursor=cursor,
        )
        stdout = merge_allow_stdout(
            rendered if cursor else stdout,
            stdout if cursor else rendered,
            event_name,
            cursor=cursor,
            harness_id=canonical_harness_id(executor),
        )
    if stdout:
        sys.stdout.write(stdout)
    return exit_code


def _context_stdout(
    context: str,
    event_name: str,
    *,
    cursor: bool,
) -> str:
    from yoke_harness.hooks.decision_render import render_context_stdout

    return render_context_stdout(context, event_name, cursor=cursor)


__all__ = ["evaluate_local_hook"]
