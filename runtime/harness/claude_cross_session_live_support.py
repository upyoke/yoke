"""Redacted fact extraction for the opt-in Claude cross-session live probe."""

from __future__ import annotations

import json
from pathlib import Path
import re
from uuid import UUID

from runtime.harness.test_claude_background_resume_live import _recorded_call
from yoke_harness import session_relay_claude_process as process_module


_SESSION_ID = re.compile(
    r'"session_id"\s*:\s*"([0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12})"'
)
_TOOL_USE = re.compile(r'"name"\s*:\s*"(ListAgents|SendMessage)"')
_TOOL_RESULT = re.compile(r'"type"\s*:\s*"tool_result"')
_SUMMARY_FIELDS = (
    "target_ready",
    "ready_nonce_seen",
    "direct_exit_zero",
    "direct_identity_same",
    "direct_response_observed",
    "direct_logs_observed",
    "direct_same_target",
    "peer_safe_after_direct",
    "sender_exit_zero",
    "sender_identity_distinct",
    "sender_not_registered",
    "same_target",
    "saw_working",
    "target_idle_after",
    "wake_observed",
    "response_observed",
    "cleanup_ok",
    "cleanup_identity_exact",
    "root_removed",
)


def agent_rows(output: str) -> list[dict[str, object]]:
    try:
        document = json.loads(output)
    except (TypeError, ValueError):
        return []
    if isinstance(document, dict):
        document = document.get("agents", document.get("sessions"))
    if not isinstance(document, list):
        return []
    return [row for row in document if isinstance(row, dict)]


def target_row(
    output: str,
    *,
    short_id: str,
    session_id: str,
    name: str,
) -> tuple[dict[str, object], int]:
    named = [row for row in agent_rows(output) if str(row.get("name") or "") == name]
    matched = [
        row
        for row in named
        if str(row.get("id") or "") == short_id
        and str(row.get("sessionId") or "") == session_id
    ]
    return (matched[0] if len(matched) == 1 else {}), len(named)


def mature_receiver(row: dict[str, object]) -> bool:
    return row.get("state") == "done" and bool(row.get("pid"))


def sender_facts(output: str) -> tuple[set[str], set[str], int]:
    return (
        set(_SESSION_ID.findall(output)),
        set(_TOOL_USE.findall(output)),
        len(_TOOL_RESULT.findall(output)),
    )


def short_id_absent(output: str, short_id: str) -> bool:
    return all(str(row.get("id") or "") != short_id for row in agent_rows(output))


def redacted_summary(namespace: dict[str, object], *, passed: bool) -> dict[str, bool]:
    result = {name: bool(namespace.get(name)) for name in _SUMMARY_FIELDS}
    result["private_capture_retained"] = not passed
    return result


def single_sender_uuid(output: str) -> str | None:
    valid = set()
    for identity in sender_facts(output)[0]:
        try:
            valid.add(str(UUID(identity)))
        except (TypeError, ValueError, AttributeError):
            continue
    return valid.pop() if len(valid) == 1 else None


class ScopedNativeProbe:
    def __init__(self, executable: str, project: Path, environment, capture) -> None:
        self.executable = executable
        self.project = project
        self.environment = environment
        self.capture = capture

    def command(self, label: str, *argv: str, timeout: int = 20):
        return _recorded_call(
            self.capture,
            label,
            lambda: process_module.run_bounded_claude_process(
                argv,
                cwd=self.project,
                environment=self.environment,
                timeout_seconds=timeout,
            ),
        )

    def roster(self, label: str):
        return self.command(
            label,
            self.executable,
            "agents",
            "--cwd",
            str(self.project),
            "--all",
            "--json",
        )
