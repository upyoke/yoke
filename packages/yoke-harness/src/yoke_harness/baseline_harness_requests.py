"""Real, tiny harness requests replacing golden-baseline login-status probes."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import shlex
from typing import Sequence

PROBE_REPLY = "OK"
PROBE_PROMPT = f"Reply exactly {PROBE_REPLY}. Do not use any tools."
REQUEST_WORKSPACE = "/tmp"


@dataclass(frozen=True)
class HarnessRequest:
    name: str
    argv: tuple[str, ...]
    login_argv: tuple[str, ...]

    @property
    def recovery(self) -> str:
        return f"Re-sign-in to {self.name} with `{shlex.join(self.login_argv)}`, then retry."

    def answered(self, stdout: str) -> bool:
        """Require a successful native response with no tool calls; discard output."""
        try:
            events = [json.loads(line) for line in stdout.splitlines() if line.strip()]
        except (TypeError, ValueError):
            return False
        if not events or any(not isinstance(event, dict) for event in events):
            return False
        answer = None
        completed = False
        for event in events:
            kind = event.get("type")
            if kind in {"tool_call", "error", "turn.failed"}:
                return False
            if kind in {"item.started", "item.completed"}:
                item = event.get("item", {})
                if not isinstance(item, dict) or item.get("type") not in {
                    "agent_message",
                    "reasoning",
                }:
                    return False
                if kind == "item.completed" and item.get("type") == "agent_message":
                    answer = item.get("text")
            if kind == "assistant":
                message = event.get("message")
                if not isinstance(message, dict):
                    return False
                content = message.get("content", [])
                if not isinstance(content, list) or any(
                    not isinstance(block, dict) or block.get("type") == "tool_use"
                    for block in content
                ):
                    return False
            if kind == "result":
                if event.get("is_error") or event.get("subtype") != "success":
                    return False
                answer = event.get("result")
                completed = True
            if kind == "turn.completed":
                completed = True
        return completed and isinstance(answer, str) and answer.strip() == PROBE_REPLY


def harness_request(argv: Sequence[str]) -> HarnessRequest | None:
    """The declared absolute executable selects a thin native CLI adapter."""
    program = argv[0]
    executable = PurePosixPath(program).name
    if executable == "claude":
        return HarnessRequest(
            "Claude",
            (
                program,
                "--safe-mode",
                "--print",
                "--tools",
                "",
                "--strict-mcp-config",
                "--output-format",
                "stream-json",
                "--verbose",
                PROBE_PROMPT,
            ),
            (program, "auth", "login"),
        )
    if executable == "codex":
        return HarnessRequest(
            "Codex",
            (
                program,
                "exec",
                "--ignore-user-config",
                "--ephemeral",
                "--skip-git-repo-check",
                "--sandbox",
                "read-only",
                "--cd",
                REQUEST_WORKSPACE,
                "--disable",
                "shell_tool",
                "--json",
                PROBE_PROMPT,
            ),
            (program, "login"),
        )
    if executable == "cursor-agent":
        return HarnessRequest(
            "Cursor",
            (
                program,
                "--print",
                "--mode",
                "ask",
                "--workspace",
                REQUEST_WORKSPACE,
                "--output-format",
                "stream-json",
                PROBE_PROMPT,
            ),
            (program, "login"),
        )
    return None
