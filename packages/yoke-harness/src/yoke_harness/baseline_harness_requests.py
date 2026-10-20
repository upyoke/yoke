"""Real, tiny harness requests replacing golden-baseline login-status probes."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import PurePosixPath
import re
import shlex
from typing import Any, Sequence

from yoke_harness.baseline_native_failures import NATIVE_FAILURES, native_failure_cause

PROBE_REPLY = "OK"
PROBE_PROMPT = f"Reply exactly {PROBE_REPLY}. Do not use any tools."
REQUEST_WORKSPACE = "/tmp"
REJECTION_EVENT_TYPE_LIMIT = 40
#: Cursor ask mode has no flag that disables tools. These inspection calls
#: may precede an exact OK reply; write and shell calls still reject.
_CURSOR_READ_ONLY_TOOL_CALLS = frozenset(
    {"readToolCall", "grepToolCall", "lsToolCall", "globToolCall"}
)
_TOKEN = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}")
_FINAL_EVENT_FIELDS = {"type", "subtype", "is_error", "answer_type", "answer_length"}
#: A rejected reply's sanitized record; the probe adds the harness exit code.
REJECTION_RECORD_FIELDS = {
    "harness",
    "rejection",
    "event_count",
    "event_types",
    "final_event",
    "exact_ok_reply",
    "tool_use",
    "degraded_context",
    "harness_exit_code",
}


@dataclass(frozen=True)
class HarnessRequest:
    name: str
    argv: tuple[str, ...]
    login_argv: tuple[str, ...]

    @property
    def recovery(self) -> str:
        return f"Re-sign-in to {self.name} with `{shlex.join(self.login_argv)}`, then retry."

    def native_refusal(self, stdout: str, stderr: str) -> dict[str, str] | None:
        """Classify fixed native refusals without recording account output."""
        cause = native_failure_cause(stdout, stderr)
        if cause is None or (
            cause == "cursor_workspace_trust_required" and self.name != "Cursor"
        ):
            return None
        reason, recovery = NATIVE_FAILURES[cause]
        if cause == "probe_auth_rejected":
            recovery = self.recovery
        return {
            "cause": cause,
            "reason": f"{self.name} real request failed: {reason}. {recovery}",
            "recovery": recovery,
        }

    def only_tool_call_rejected(self, stdout: str) -> bool:
        """True when a Cursor stream's sole fault is a non-inspection tool call.

        The reply was otherwise an exact OK with a successful completion, so
        one retry tells a rare tool call from a steady one.
        """
        return self.name == "Cursor" and self._reply_review(stdout, 0)[0] == [
            "tool_call_event"
        ]

    def reply_rejection(
        self, stdout: str, *, exit_code: int = 0
    ) -> dict[str, Any] | None:
        """Accept an exact OK reply, or describe why the stream was rejected.

        Cursor may call read-only tools before that reply. Write, shell, and
        any other tool call still reject, and ``tool_use`` stays true on the
        record whenever a tool call was present. A ``tool_call`` event type
        names its payload kind (``tool_call:shellToolCall``). The record is
        sanitized: event types, the final event's shape and booleans, never
        reply text, account output or a transcript.
        """
        return self._reply_review(stdout, exit_code)[1]

    def _reply_review(
        self, stdout: str, exit_code: int
    ) -> tuple[list[str], dict[str, Any] | None]:
        """Return every distinct rejection branch, in order, and the record."""
        lines = [line for line in stdout.splitlines() if line.strip()]
        types: list[str] = []
        branches = [] if lines else ["no_events"]
        answer = None
        completed = degraded = tool_use = False
        final: dict[str, Any] | None = None

        def reject(branch: str) -> None:
            if branch not in branches:
                branches.append(branch)

        for line in lines:
            try:
                event = json.loads(line)
            except ValueError:
                event = None
            if not isinstance(event, dict):
                degraded = True
                types.append("<not-an-event>")
                reject("malformed_stream")
                continue
            kind = event.get("type")
            types.append(_token(kind))
            if kind in {"error", "turn.failed"}:
                reject(kind.replace(".", "_") + "_event")
            if kind == "tool_call":
                tool_use = True
                types[-1] = _tool_call_label(event)
                if self.name != "Cursor" or not _cursor_tool_call_is_read_only(event):
                    reject("tool_call_event")
            if kind in {"item.started", "item.completed"}:
                item = event.get("item", {})
                if not isinstance(item, dict):
                    reject("item_malformed")
                elif item.get("type") not in {"agent_message", "reasoning"}:
                    tool_use = tool_use or isinstance(item.get("type"), str)
                    reject("item_not_a_message")
                elif kind == "item.completed" and item.get("type") == "agent_message":
                    answer = item.get("text")
            if kind == "assistant":
                message = event.get("message")
                content = (
                    message.get("content", []) if isinstance(message, dict) else None
                )
                if not isinstance(content, list) or any(
                    not isinstance(block, dict) for block in content
                ):
                    reject("assistant_message_malformed")
                elif any(block.get("type") == "tool_use" for block in content):
                    tool_use = True
                    reject("assistant_tool_use")
            if kind == "result":
                if event.get("is_error") or event.get("subtype") != "success":
                    reject("result_error")
                answer = event.get("result")
                completed = True
                final = event
            if kind == "turn.completed":
                completed = True
                final = event
        exact = isinstance(answer, str) and answer.strip() == PROBE_REPLY
        if not completed:
            reject("no_completion_event")
        elif not exact:
            reject("reply_not_exact")
        if exit_code:
            reject("native_exit_nonzero")
        if not branches:
            return branches, None
        return branches, {
            "harness": self.name,
            "rejection": branches[0],
            "event_count": len(lines),
            "event_types": types[:REJECTION_EVENT_TYPE_LIMIT],
            "final_event": None
            if final is None
            else {
                "type": _token(final.get("type")),
                "subtype": _token(final.get("subtype")),
                "is_error": final.get("is_error")
                if isinstance(final.get("is_error"), bool)
                else None,
                "answer_type": type(answer).__name__,
                "answer_length": len(answer) if isinstance(answer, str) else None,
            },
            "exact_ok_reply": exact,
            "tool_use": tool_use,
            # Lines that were not JSON event objects: the stream itself was damaged.
            "degraded_context": degraded,
        }


def _cursor_tool_call_is_read_only(event: dict) -> bool:
    """True only when every payload key is a known Cursor inspection tool."""
    payload = event.get("tool_call")
    if not isinstance(payload, dict) or not payload:
        return False
    return set(payload) <= _CURSOR_READ_ONLY_TOOL_CALLS


def _tool_call_label(event: dict) -> str | None:
    """Name a tool call event by its payload kind, such as ``tool_call:readToolCall``."""
    payload = event.get("tool_call")
    if not isinstance(payload, dict) or not payload:
        return "tool_call"
    return _token("tool_call:" + ".".join(sorted(str(key) for key in payload)))


def _token(value: object) -> str | None:
    """Keep a harness event label only when it is a short identifier."""
    if value is None:
        return None
    if isinstance(value, str) and _TOKEN.fullmatch(value):
        return value
    return "<other>"


def read_rejection_record(stdout: str) -> dict[str, Any] | None:
    """Accept a sealed program's printed record only in its exact sanitized shape."""
    lines = [line for line in stdout.splitlines() if line.strip()]
    try:
        record = json.loads(lines[-1]) if lines else None
    except ValueError:
        return None
    if not isinstance(record, dict) or set(record) != REJECTION_RECORD_FIELDS:
        return None
    final = record["final_event"]
    types = record["event_types"]
    valid = (
        record["harness"] in {"Claude", "Codex", "Cursor"}
        and _token(record["rejection"]) == record["rejection"]
        and all(
            isinstance(record[key], bool)
            for key in ("exact_ok_reply", "tool_use", "degraded_context")
        )
        and all(
            isinstance(record[key], int) and not isinstance(record[key], bool)
            for key in ("event_count", "harness_exit_code")
        )
        and isinstance(types, list)
        and len(types) <= REJECTION_EVENT_TYPE_LIMIT
        and all(t is None or t == _token(t) or t == "<not-an-event>" for t in types)
        and (
            final is None
            or (
                isinstance(final, dict)
                and set(final) == _FINAL_EVENT_FIELDS
                and _token(final["type"]) == final["type"]
                and _token(final["subtype"]) == final["subtype"]
                and final["is_error"] in (True, False, None)
                and _token(final["answer_type"]) == final["answer_type"]
                and (
                    final["answer_length"] is None
                    or isinstance(final["answer_length"], int)
                )
            )
        )
    )
    return record if valid else None


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
    if executable in {"cursor-agent", "agent"}:
        return HarnessRequest(
            "Cursor",
            (
                program,
                "--print",
                "--mode",
                "ask",
                "--trust",
                "--workspace",
                REQUEST_WORKSPACE,
                "--output-format",
                "stream-json",
                PROBE_PROMPT,
            ),
            (program, "login"),
        )
    return None
