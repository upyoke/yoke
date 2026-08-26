"""Claude native invocation construction and relay-owned process starts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
from typing import Callable

from yoke_contracts.session_control.launch_permission_bypass import (
    CLAUDE_BYPASS_ARGUMENTS,
)
from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV
from yoke_harness.session_relay_claude_identity import resolve_background_agent
from yoke_harness.session_relay_claude_process import (
    ClaudeProcessResult,
    run_bounded_claude_process,
)
from yoke_harness.session_relay_claude_resume import (
    ClaudeResumeProcess,
    spawn_detached_claude_resume,
)
from yoke_harness.session_relay_environment import native_session_environment
from yoke_harness.session_relay_runtime import RelayExecutionContext


CLAUDE_NATIVE_TIMEOUT_SECONDS = 20
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

    @property
    def argv(self) -> tuple[str, ...]:
        if self.resume:
            return (
                self.executable,
                "-p",
                *CLAUDE_BYPASS_ARGUMENTS,
                "--resume",
                self.session_id,
                self.instruction,
                "--output-format",
                "json",
            )
        arguments = [
            self.executable,
            "--session-id",
            self.session_id,
            *CLAUDE_BYPASS_ARGUMENTS,
        ]
        if self.model:
            arguments.extend(("--model", self.model))
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
        timeout_seconds=CLAUDE_NATIVE_TIMEOUT_SECONDS,
    )


def run_claude_process(invocation: ClaudeNativeInvocation) -> ClaudeProcessResult:
    """Run one launch command with private bounded output."""
    return _run_claude_command(invocation, invocation.argv)


def lookup_claude_session(invocation: ClaudeNativeInvocation) -> ClaudeProcessResult:
    return _run_claude_command(
        invocation,
        (invocation.executable, *CLAUDE_AGENT_LIST_ARGUMENTS),
    )


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
    )


__all__ = [
    "CLAUDE_AGENT_LIST_ARGUMENTS",
    "CLAUDE_BACKGROUND_STOP_COMMAND",
    "CLAUDE_NATIVE_TIMEOUT_SECONDS",
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
]
