"""Claude native invocation construction and relay-owned process starts."""

from __future__ import annotations

import shutil
from typing import Callable
from uuid import uuid4

from yoke_contracts.session_control.launch_registration import (
    NATIVE_LAUNCH_WORKSPACE_FIELD,
)
from yoke_contracts.session_control.model_selection import (
    LaunchModelSelection,
    native_model_selector,
)
from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV
from yoke_harness.session_relay_claude_invocation import ClaudeNativeInvocation
from yoke_harness.session_relay_native_spawn import (
    SupervisedNative,
    spawn_supervised_native,
)
from yoke_harness.session_relay_environment import native_session_environment
from yoke_harness.session_relay_runtime import RelayExecutionContext


ClaudeNativeSpawner = Callable[["ClaudeNativeInvocation"], SupervisedNative | None]
ClaudeWakeSpawner = Callable[
    [RelayExecutionContext, "ClaudeNativeInvocation"], SupervisedNative | None
]
ExecutableFinder = Callable[[str], str | None]


def discover_claude_cli(finder: ExecutableFinder | None = None) -> str | None:
    """Return the executable selected by the local command search path."""
    try:
        discovered = (finder or shutil.which)("claude")
    except (OSError, ValueError):
        return None
    return str(discovered).strip() if discovered else None


def _environment(invocation: ClaudeNativeInvocation) -> dict[str, str]:
    return native_session_environment(
        executor="claude-code",
        provider="anthropic",
        model=invocation.model,
        markers={"CLAUDE_CODE_ENTRYPOINT": "cli"},
        launch_id=invocation.launch_id,
        launch_attestation=invocation.launch_attestation,
    )


def _launch_progress(
    invocation: ClaudeNativeInvocation,
    started: SupervisedNative,
) -> None:
    reporter = invocation.progress_reporter
    if reporter is None:
        return
    try:
        reporter(
            {
                "surface": "claude-cli",
                "result_code": "native_spawn_pending",
                "native_launch_phase": "spawn_started",
                "native_launch_pid": started.pid,
                NATIVE_LAUNCH_WORKSPACE_FIELD: str(invocation.cwd),
                **started.evidence,
            }
        )
    except Exception:
        pass


def spawn_claude_create(
    invocation: ClaudeNativeInvocation,
) -> SupervisedNative | None:
    """Start the session's first turn as a process this relay owns."""
    started = spawn_supervised_native(
        invocation.argv,
        checkout=invocation.cwd,
        environment=_environment(invocation),
        attempt_id=str(invocation.launch_id or ""),
        native_session_id=invocation.session_id,
        binary_source="path",
        supervision_kind="launch",
    )
    if started is not None:
        _launch_progress(invocation, started)
    return started


def spawn_claude_wake(
    context: RelayExecutionContext,
    invocation: ClaudeNativeInvocation,
) -> SupervisedNative | None:
    """Resume a stopped conversation in a fresh process the relay owns.

    Nothing holds the conversation open between turns, so the resume never has
    to argue with a second owner for it: the previous turn's process is gone,
    and this one starts where it left off.
    """
    environment = _environment(invocation)
    environment[RESUME_ATTEMPT_ENV] = context.job_id
    return spawn_supervised_native(
        invocation.argv,
        checkout=invocation.cwd,
        environment=environment,
        attempt_id=context.job_id,
        native_session_id=invocation.session_id,
        binary_source="path",
        lease_id=context.lease_id,
    )


def native_invocation(
    context: RelayExecutionContext,
    executable: str,
    instruction: str,
) -> ClaudeNativeInvocation | None:
    launch = context.job_kind == "launch"
    # A create mints the conversation id it is about to start; every retry of
    # one launch therefore starts a session of its own, and no attempt inherits
    # an id another attempt already used.
    session_id = str(uuid4()) if launch else str(context.target_session_id or "")
    if not session_id.strip():
        return None
    raw_model = getattr(context, "requested_model", None) if launch else None
    raw_effort = (
        getattr(context, "requested_reasoning_effort", None) if launch else None
    )
    raw_context = (
        getattr(context, "requested_context_window_tokens", None) if launch else None
    )
    selection = LaunchModelSelection(
        str(raw_model).strip() if raw_model else None,
        str(raw_effort).strip() if raw_effort else None,
        int(raw_context) if raw_context is not None else None,
    )
    return ClaudeNativeInvocation(
        executable,
        context.checkout,
        session_id,
        str(context.surface_version),
        instruction,
        resume=not launch,
        launch_id=context.job_id if launch else None,
        model=native_model_selector("claude-cli", selection),
        reasoning_effort=selection.reasoning_effort,
        presentation=context.presentation,
        session_name=context.session_name if launch else None,
        launch_attestation=context.launch_attestation if launch else None,
        progress_reporter=context.launch_progress_reporter if launch else None,
    )


__all__ = [
    "ClaudeNativeInvocation",
    "ClaudeNativeSpawner",
    "ClaudeWakeSpawner",
    "ExecutableFinder",
    "discover_claude_cli",
    "native_invocation",
    "spawn_claude_create",
    "spawn_claude_wake",
]
