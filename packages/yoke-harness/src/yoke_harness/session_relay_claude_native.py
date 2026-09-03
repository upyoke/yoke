"""Claude native invocation construction and relay-owned process starts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import json
import shutil
from typing import Callable, Mapping
from uuid import uuid4

from yoke_contracts.session_control.launch_permission_bypass import (
    CLAUDE_BYPASS_ARGUMENTS,
)
from yoke_contracts.session_control.launch_registration import (
    NATIVE_LAUNCH_WORKSPACE_FIELD,
)
from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV
from yoke_contracts.session_control.presentation import (
    CLAUDE_LOCAL_PRESENTATION,
    CLAUDE_REMOTE_CONTROL_SETTING,
)
from yoke_harness.session_relay_native_spawn import (
    SupervisedNative,
    spawn_supervised_native,
)
from yoke_harness.session_relay_environment import native_session_environment
from yoke_harness.session_relay_runtime import RelayExecutionContext


@dataclass(frozen=True)
class ClaudeNativeInvocation:
    """One native command, its workspace, and the session it names.

    ``session_id`` is the conversation the native will run in — chosen by the
    relay on a create, and the target's own id on a wake. ``launch_id`` is the
    launch that asked for a create, and is what custody and the attestation are
    keyed on; a wake has no launch and leaves it unset.
    """

    executable: str
    cwd: Path
    session_id: str
    surface_version: str
    instruction: str = field(repr=False)
    resume: bool = False
    launch_id: str | None = None
    model: str | None = None
    presentation: str | None = None
    session_name: str | None = None
    launch_attestation: str | None = field(default=None, repr=False)
    progress_reporter: Callable[[Mapping[str, object]], bool] | None = field(
        default=None, repr=False, compare=False
    )

    @property
    def settings_arguments(self) -> tuple[str, ...]:
        if self.presentation != CLAUDE_LOCAL_PRESENTATION:
            return ()
        settings = json.dumps(
            {CLAUDE_REMOTE_CONTROL_SETTING: True},
            separators=(",", ":"),
        )
        return "--settings", settings

    @property
    def argv(self) -> tuple[str, ...]:
        arguments = [
            self.executable,
            "-p",
            *CLAUDE_BYPASS_ARGUMENTS,
            *self.settings_arguments,
        ]
        if self.resume:
            arguments.extend(("--resume", self.session_id))
        else:
            # The relay names the conversation instead of discovering it, so a
            # create knows its own session before the native's first hook runs.
            arguments.extend(("--session-id", self.session_id))
            if self.model:
                arguments.extend(("--model", self.model))
            if self.session_name:
                arguments.extend(("--name", self.session_name))
        arguments.extend((self.instruction, "--output-format", "json"))
        return tuple(arguments)


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
    return ClaudeNativeInvocation(
        executable,
        context.checkout,
        session_id,
        str(context.surface_version),
        instruction,
        resume=not launch,
        launch_id=context.job_id if launch else None,
        model=str(raw_model).strip() if raw_model else None,
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
