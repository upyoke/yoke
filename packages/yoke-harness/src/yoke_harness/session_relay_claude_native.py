"""Claude native invocation construction and relay-owned process starts."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
import shutil
from typing import Callable

from yoke_contracts.session_control.resume import RESUME_ATTEMPT_ENV
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
                "--resume",
                self.session_id,
                self.instruction,
                "--output-format",
                "json",
            )
        arguments = [self.executable, "--session-id", self.session_id]
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
        executor_version=invocation.surface_version,
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
        (invocation.executable, "agents", "--all", "--json"),
    )


def spawn_claude_wake(
    context: RelayExecutionContext,
    invocation: ClaudeNativeInvocation,
) -> ClaudeResumeProcess | None:
    environment = _environment(invocation)
    environment[RESUME_ATTEMPT_ENV] = context.job_id
    return spawn_detached_claude_resume(
        invocation.argv,
        checkout=invocation.cwd,
        environment=environment,
        attempt_id=context.job_id,
        native_session_id=invocation.session_id,
        binary_source="path",
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
