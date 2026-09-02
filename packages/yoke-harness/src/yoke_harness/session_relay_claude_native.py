"""Claude native invocation construction and relay-owned process starts."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import json
import shutil
from typing import Callable, Mapping

from yoke_contracts.session_control.launch_permission_bypass import (
    CLAUDE_BYPASS_ARGUMENTS,
)
from yoke_contracts.session_control.capabilities import native_create_timeout_seconds
from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV
from yoke_contracts.session_control.presentation import (
    CLAUDE_LOCAL_PRESENTATION,
    CLAUDE_REMOTE_CONTROL_SETTING,
)
from yoke_harness.session_relay_claude_identity import (
    CLAUDE_IDENTITY_LOOKUP_ATTEMPTS,
    CLAUDE_IDENTITY_RETRY_SECONDS,
    resolve_background_agent,
)
from yoke_harness.session_relay_claude_process import (
    ClaudeProcessResult,
    run_bounded_claude_process,
)
from yoke_harness.session_relay_claude_resume import (
    ClaudeResumeProcess,
    spawn_detached_claude_resume,
)
from yoke_harness.session_relay_environment import native_session_environment
from yoke_harness.session_relay_report_delivery import RELAY_REPORT_TIMEOUT_SECONDS
from yoke_harness.session_relay_runtime import RelayExecutionContext


CLAUDE_NATIVE_COMMAND_TIMEOUT_SECONDS = 20
CLAUDE_CREATE_TIMEOUT_SECONDS = native_create_timeout_seconds("claude-cli")
if CLAUDE_CREATE_TIMEOUT_SECONDS is None:
    raise RuntimeError("claude-cli manifest has no native create timeout")
CLAUDE_CREATE_HANDOFF_RESERVE_SECONDS = (
    CLAUDE_IDENTITY_LOOKUP_ATTEMPTS * CLAUDE_NATIVE_COMMAND_TIMEOUT_SECONDS
    + (CLAUDE_IDENTITY_LOOKUP_ATTEMPTS - 1) * CLAUDE_IDENTITY_RETRY_SECONDS
    + RELAY_REPORT_TIMEOUT_SECONDS
)
CLAUDE_AGENT_LIST_ARGUMENTS = ("agents", "--all", "--json")
CLAUDE_BACKGROUND_STOP_COMMAND = "stop"


@dataclass(frozen=True)
class ClaudeNativeInvocation:
    executable: str
    cwd: Path
    session_id: str
    surface_version: str
    instruction: str = field(repr=False)
    resume: bool = False
    model: str | None = None
    presentation: str | None = None
    session_name: str | None = None
    launch_deadline_at: str | None = None
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
        if self.resume:
            return (
                self.executable,
                "-p",
                *CLAUDE_BYPASS_ARGUMENTS,
                *self.settings_arguments,
                "--resume",
                self.session_id,
                self.instruction,
                "--output-format",
                "json",
            )
        arguments = [self.executable, *CLAUDE_BYPASS_ARGUMENTS, *self.settings_arguments]
        if self.model:
            arguments.extend(("--model", self.model))
        if self.session_name:
            arguments.extend(("--name", self.session_name))
        arguments.extend(("--bg", self.instruction))
        return tuple(arguments)


ClaudeProcessRunner = Callable[[ClaudeNativeInvocation], ClaudeProcessResult]
ClaudeWakeSpawner = Callable[
    [RelayExecutionContext, ClaudeNativeInvocation], ClaudeResumeProcess | None
]
ClaudeSessionLookup = Callable[[ClaudeNativeInvocation], ClaudeProcessResult]
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
    )


def _run_claude_command(
    invocation: ClaudeNativeInvocation,
    argv: tuple[str, ...],
) -> ClaudeProcessResult:
    return run_bounded_claude_process(
        argv,
        cwd=invocation.cwd,
        environment=_environment(invocation),
        timeout_seconds=CLAUDE_NATIVE_COMMAND_TIMEOUT_SECONDS,
    )


def _deadline_budget(raw: str | None) -> float | None:
    try:
        deadline = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if deadline.tzinfo is None:
        deadline = deadline.replace(tzinfo=timezone.utc)
    remaining = (deadline - datetime.now(timezone.utc)).total_seconds()
    return max(0.1, remaining - CLAUDE_CREATE_HANDOFF_RESERVE_SECONDS)


def _launch_progress(
    invocation: ClaudeNativeInvocation,
    *,
    pid: int,
    phase: str,
    duration_ms: int | None = None,
) -> None:
    evidence: dict[str, object] = {
        "surface": "claude-cli",
        "result_code": "native_spawn_pending",
        "native_launch_phase": phase,
        "native_launch_pid": pid,
        "native_launch_bound_seconds": int(CLAUDE_CREATE_TIMEOUT_SECONDS),
    }
    if duration_ms is not None:
        evidence["duration_ms"] = duration_ms
    reporter = invocation.progress_reporter
    if reporter is not None:
        try:
            reporter(evidence)
        except Exception:
            pass


def _supervise_launch(invocation: ClaudeNativeInvocation, pid: int) -> None:
    from yoke_harness.session_launch_containment import record_supervised_native

    if not record_supervised_native(invocation.session_id, pid):
        raise RuntimeError(
            "native launch supervision unavailable; inspect relay custody before retry"
        )
    _launch_progress(invocation, pid=pid, phase="spawn_started")


def _contain_launch(invocation: ClaudeNativeInvocation, _pid: int) -> None:
    from yoke_harness.session_launch_containment import contain_launch_native

    contain_launch_native(invocation.session_id, reason="launch_deadline")


def run_claude_process(invocation: ClaudeNativeInvocation) -> ClaudeProcessResult:
    """Run one create through its soft manifest bound and launch deadline."""
    hard_timeout = _deadline_budget(invocation.launch_deadline_at)
    soft_timeout = float(CLAUDE_CREATE_TIMEOUT_SECONDS)
    hard_timeout = soft_timeout if hard_timeout is None else hard_timeout
    soft_timeout = min(soft_timeout, hard_timeout)
    return run_bounded_claude_process(
        invocation.argv,
        cwd=invocation.cwd,
        environment=_environment(invocation),
        timeout_seconds=soft_timeout,
        continue_while_alive=True,
        hard_timeout_seconds=hard_timeout,
        on_started=lambda pid: _supervise_launch(invocation, pid),
        on_bound_exceeded=lambda pid, duration: _launch_progress(
            invocation, pid=pid, phase="spawn_alive", duration_ms=duration
        ),
        on_hard_timeout=lambda pid: _contain_launch(invocation, pid),
        start_new_session=True,
    )


def lookup_claude_session(invocation: ClaudeNativeInvocation) -> ClaudeProcessResult:
    return _run_claude_command(
        invocation,
        (invocation.executable, *CLAUDE_AGENT_LIST_ARGUMENTS),
    )


def stop_claude_background(
    invocation: ClaudeNativeInvocation,
    short_id: str,
) -> None:
    """Best-effort stop of a native created without a valid handoff."""
    try:
        _run_claude_command(
            invocation,
            (invocation.executable, CLAUDE_BACKGROUND_STOP_COMMAND, short_id),
        )
    except Exception:
        pass


def _release_background_job(
    invocation: ClaudeNativeInvocation,
    session_lookup: ClaudeSessionLookup,
) -> dict[str, str]:
    """Free the conversation so the wake turn can carry its prompt.

    A wake only delivers because the resumed turn runs a prompt: the prompt
    is what fires a hook, and the hook is what injects the pending envelope.
    A background job holds its conversation open and the native refuses a
    headless resume of one that is still running, so the job is stopped
    first — that keeps the transcript, and the prompt then lands on the same
    session id instead of on a fork. Only a session the wake scheduler has
    already found non-active reaches here, so no working agent is stopped.

    Returns the bounded facts recorded on the attempt's evidence.
    """
    resolution = resolve_background_agent(
        invocation.session_id,
        lambda: session_lookup(invocation),
    )
    evidence = {"background_agent_result": resolution.result_code}
    if resolution.short_id is None:
        return evidence
    try:
        stopped = _run_claude_command(
            invocation,
            (
                invocation.executable,
                CLAUDE_BACKGROUND_STOP_COMMAND,
                resolution.short_id,
            ),
        )
    except Exception:  # native exception text can carry private output
        return {**evidence, "background_agent_stop": "native_exception"}
    # The resume runs either way: the job may have exited on its own between
    # the listing and the stop. When it truly still holds the conversation
    # the native refuses, and that refusal settles the attempt with its
    # captured reason rather than reporting a silent success.
    outcome = "completed" if stopped.returncode == 0 else "native_exit"
    return {**evidence, "background_agent_stop": outcome}


def spawn_claude_wake(
    context: RelayExecutionContext,
    invocation: ClaudeNativeInvocation,
    *,
    session_lookup: ClaudeSessionLookup = lookup_claude_session,
) -> ClaudeResumeProcess | None:
    background_job = _release_background_job(invocation, session_lookup)
    environment = _environment(invocation)
    environment[RESUME_ATTEMPT_ENV] = context.job_id
    return spawn_detached_claude_resume(
        invocation.argv,
        checkout=invocation.cwd,
        environment=environment,
        attempt_id=context.job_id,
        native_session_id=invocation.session_id,
        binary_source="path",
        lease_id=context.lease_id,
        background_job=background_job,
    )


def native_invocation(
    context: RelayExecutionContext,
    executable: str,
    instruction: str,
) -> ClaudeNativeInvocation | None:
    launch = context.job_kind == "launch"
    session_id = context.job_id if launch else str(context.target_session_id or "")
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
        model=str(raw_model).strip() if raw_model else None,
        presentation=context.presentation,
        session_name=context.session_name if launch else None,
        launch_deadline_at=context.launch_deadline_at if launch else None,
        launch_attestation=context.launch_attestation if launch else None,
        progress_reporter=context.launch_progress_reporter if launch else None,
    )


__all__ = [
    "CLAUDE_AGENT_LIST_ARGUMENTS",
    "CLAUDE_BACKGROUND_STOP_COMMAND",
    "CLAUDE_CREATE_TIMEOUT_SECONDS",
    "CLAUDE_CREATE_HANDOFF_RESERVE_SECONDS",
    "CLAUDE_NATIVE_COMMAND_TIMEOUT_SECONDS",
    "ClaudeNativeInvocation",
    "ClaudeProcessRunner",
    "ClaudeSessionLookup",
    "ClaudeWakeSpawner",
    "ExecutableFinder",
    "discover_claude_cli",
    "lookup_claude_session",
    "native_invocation",
    "run_claude_process",
    "spawn_claude_wake",
    "stop_claude_background",
]
