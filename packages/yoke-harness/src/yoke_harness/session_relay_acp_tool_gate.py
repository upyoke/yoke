"""Client-side PreToolUse gating for relay-supervised native tool calls.

A native the relay supervises over ACP does not run Yoke's hooks: the relay
holds the connection and answers the agent's tool requests itself, so nothing
in the child's own process consults the guard chain. Left ungated, a
supervised session executes commands that an ordinary registered session
would be refused — the destructive-git guard, the worktree write authority
check, and every other PreToolUse lint simply never see the call.

The relay therefore runs the same ``yoke hook evaluate PreToolUse`` chain
before approving each request, with the request rendered into the payload
shape the guards already read. The decision is read from the chain's stdout
verdict rather than its exit code alone, because that code is
executor-dependent while the verdict document is not.

Gating fails closed. A supervised native exists precisely because nobody is
watching it, so a chain that cannot be consulted is a refusal, not a pass.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import shlex
import subprocess
from typing import Any, Callable, Mapping, Sequence


GATE_EVENT = "PreToolUse"
GATE_TOOL_NAME = "Bash"
GATE_TIMEOUT_SECONDS = 20.0
_MAX_VERDICT_BYTES = 256 * 1024

CommandRunner = Callable[..., subprocess.CompletedProcess[str]]


@dataclass(frozen=True)
class ToolGateDecision:
    """One allow/deny verdict plus the reason a refusal should carry back."""

    allowed: bool
    reason: str = ""


def _payload(command: Sequence[str], cwd: Path) -> str:
    return json.dumps(
        {
            "hook_event_name": GATE_EVENT,
            "tool_name": GATE_TOOL_NAME,
            "tool_input": {"command": shlex.join(command)},
            "cwd": str(cwd),
        },
        separators=(",", ":"),
    )


def _denial_reason(stdout: str) -> str | None:
    """Return the refusal reason a guard verdict carries, or ``None``.

    Two shapes reach here — the Cursor verdict and the ``hookSpecificOutput``
    envelope — because the chain renders whichever the calling executor reads.
    """
    for line in stdout.splitlines():
        text = line.strip()
        if not text.startswith("{"):
            continue
        try:
            document = json.loads(text)
        except ValueError:
            continue
        if not isinstance(document, dict):
            continue
        if str(document.get("permission") or "").lower() == "deny":
            return str(document.get("agent_message") or "refused by guard chain")
        nested = document.get("hookSpecificOutput")
        if isinstance(nested, dict) and (
            str(nested.get("permissionDecision") or "").lower() == "deny"
        ):
            return str(
                nested.get("permissionDecisionReason") or "refused by guard chain"
            )
    return None


def evaluate_native_command(
    command: Sequence[str],
    *,
    cwd: Path,
    environ: Mapping[str, str],
    yoke_executable: str = "yoke",
    command_runner: CommandRunner = subprocess.run,
    timeout: float = GATE_TIMEOUT_SECONDS,
) -> ToolGateDecision:
    """Run the installed PreToolUse chain against one supervised command."""
    if not command:
        return ToolGateDecision(False, "supervised command is empty")
    try:
        completed = command_runner(
            [yoke_executable, "hook", "evaluate", GATE_EVENT],
            cwd=str(cwd),
            env=dict(environ),
            input=_payload(command, cwd),
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            text=True,
            timeout=timeout,
            check=False,
        )
    except (OSError, subprocess.SubprocessError) as exc:
        return ToolGateDecision(False, f"guard chain unavailable: {exc!s}")
    stdout = (completed.stdout or "")[:_MAX_VERDICT_BYTES]
    reason = _denial_reason(stdout)
    if reason is not None:
        return ToolGateDecision(False, reason)
    if completed.returncode not in (0,):
        return ToolGateDecision(False, "guard chain refused the command")
    return ToolGateDecision(True)


def permission_request_command(params: Mapping[str, Any]) -> list[str] | None:
    """Return the argv a permission request is asking to run, if it names one."""
    tool_call = params.get("toolCall")
    raw = tool_call.get("rawInput") if isinstance(tool_call, dict) else None
    if not isinstance(raw, dict):
        return None
    command = raw.get("command")
    if isinstance(command, list):
        argv = [value for value in command if isinstance(value, str)]
        return argv or None
    if isinstance(command, str) and command.strip():
        try:
            argv = shlex.split(command)
        except ValueError:
            return [command]
        return argv or [command]
    return None


__all__ = [
    "GATE_EVENT",
    "GATE_TIMEOUT_SECONDS",
    "GATE_TOOL_NAME",
    "ToolGateDecision",
    "evaluate_native_command",
    "permission_request_command",
]
