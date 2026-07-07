"""Hook payload parsing for observe telemetry."""

from __future__ import annotations

import os
import re
import shlex
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain.events_crud import normalize_event_item_id
from yoke_core.domain.observe_codex_transcript import _reconcile_codex_exit_code
from yoke_core.domain.observe_normalization import (
    _compute_duration,
    _resolve_dispatch_context,
    _resolve_explicit_refs,
    _resolve_main_session_attribution,
)


def _payload_agent_type(data: Dict[str, Any]) -> Optional[str]:
    value = data.get("agent_type")
    if isinstance(value, str) and value.strip():
        return value.strip()
    return None


@dataclass
class EventRecord:
    """Intermediate representation of a parsed hook event."""

    tool_name: str = ""
    command: str = ""
    file_path: str = ""
    exit_code: Optional[int] = None
    duration_ms: Optional[int] = None
    is_failure: bool = False
    hook_error: Optional[str] = None
    response_text: str = ""
    hook_event: Optional[str] = None

    # Attribution / context (populated by caller)
    session_id: str = ""
    item_id: Optional[str] = None
    task_num: Optional[int] = None
    agent_type: Optional[str] = None
    attribution_source: Optional[str] = None
    tool_use_id: Optional[str] = None
    turn_id: Optional[str] = None
    has_permission_decision: bool = False

    # Derived
    anomalies: List[str] = field(default_factory=list)


def parse_hook_event(
    data: Dict[str, Any],
    *,
    session_id: str = "",
    item_id: Optional[str] = None,
    task_num: Optional[int] = None,
    agent_type: Optional[str] = None,
    attribution_source: Optional[str] = None,
    hook_event: Optional[str] = None,
    tool_use_id: Optional[str] = None,
    db_path: Optional[str] = None,
    project_dir: Optional[str] = None,
) -> Optional[EventRecord]:
    """Parse a PostToolUse/PostToolUseFailure JSON payload into an EventRecord.

    Returns ``None`` when the event should be silently dropped (e.g. a
    PostToolUse hook firing for a failure -- deduplicated).
    """
    hook_error = data.get("error")
    is_failure = hook_error is not None

    # Deduplicate failed tool call events.
    if is_failure and hook_event == "PostToolUse":
        return None

    tool_name = data.get("tool_name", "") or ""
    tool_input = data.get("tool_input", {}) or {}

    command = ""
    file_path = ""
    exit_code = None

    if tool_name == "Bash":
        command = (tool_input.get("command", "") or "")[:4096]
    elif tool_name in ("Write", "Edit", "Read"):
        file_path = tool_input.get("file_path", "") or ""

    # Parse tool_response for exit code and preview
    response = data.get("tool_response", {})
    response_text = _extract_response_text(response)

    if tool_name == "Bash":
        _exit_source = response_text
        if hook_error:
            _exit_source = (_exit_source + "\n" + str(hook_error)).strip()
        exit_match = re.search(r"Exit code (\d+)", _exit_source)
        if exit_match:
            exit_code = int(exit_match.group(1))
            # A parsed nonzero exit IS a failure. Without this flip, the
            # downstream classifier still records the failure via its
            # defense-in-depth exit_code>0 branch, but is_failure stays
            # incorrectly False in the record and observe_anomaly's
            # structured_exit/benign_failure branches (which gate on
            # is_failure) never see this row. Set is_failure here so the
            # whole pipeline sees a consistent truth.
            if exit_code > 0 and not is_failure:
                is_failure = True
        elif not is_failure:
            # Defense-in-depth fallback for ambiguous Bash failure
            # shapes. A Bash PostToolUse payload with no top-level error, no
            # "Exit code N" text, but response content matching a hard-failure
            # indicator (e.g. "No such file or directory", "command not
            # found", "Permission denied") must not be recorded as a clean
            # success. Reclassify it as a failure with sentinel exit_code=1
            # so downstream telemetry stays truthful even when the runtime
            # omits the PostToolUseFailure hook.
            if (
                hook_event == "PostToolUse"
                and _contains_bash_hard_failure(response_text, command)
            ):
                is_failure = True
                exit_code = 1
            else:
                exit_code = 0

    if not tool_use_id:
        tool_use_id = data.get("tool_use_id", "") or None

    # Codex silent-failure recovery: Codex does
    # not emit a PostToolUseFailure event, and its PostToolUse payload
    # carries no native ``exit_code``/``status`` field. Commands like
    # ``false`` or ``exit 7`` produce no output at all, so neither the
    # "Exit code N" parse nor the hard-failure text fallback above catches
    # them. Reconcile against the Codex transcript JSONL as a last resort:
    # match our ``tool_use_id`` to the transcript's ``call_id`` and read
    # the ``exit_code``/``status`` fields from the corresponding
    # ``exec_command_end`` entry. Graceful degradation — any I/O or schema
    # mismatch returns ``None`` and leaves the classification unchanged.
    if (
        tool_name == "Bash"
        and hook_event == "PostToolUse"
        and not is_failure
        and (exit_code is None or exit_code == 0)
        and tool_use_id
    ):
        transcript_path = data.get("transcript_path") or ""
        if transcript_path:
            recon = _reconcile_codex_exit_code(
                str(transcript_path), str(tool_use_id)
            )
            if recon is not None:
                recon_exit, recon_status = recon
                if recon_exit != 0 or recon_status == "failed":
                    is_failure = True
                    # Preserve the true exit code when non-zero; fall back
                    # to sentinel 1 only if the transcript reported failure
                    # via ``status`` without an exit code.
                    exit_code = recon_exit if recon_exit else 1

    # Extract turn_id from hook payload
    turn_id = data.get("turn_id", "") or data.get("message_id", "") or None

    # Check for permissionDecision in payload
    has_permission_decision = "permissionDecision" in data

    if not agent_type:
        agent_type = _payload_agent_type(data)

    if not session_id:
        session_id = (
            data.get("session_id", "")  # hook payload
            or os.environ.get("YOKE_SESSION_ID", "")
            or os.environ.get("CLAUDE_SESSION_ID", "")
            or os.environ.get("CODEX_THREAD_ID", "")
        )

    if not item_id and db_path and project_dir:
        item_id, task_num, attribution_source = _resolve_dispatch_context(
            db_path, project_dir
        )

    if not item_id and db_path and project_dir:
        item_id, attribution_source = _resolve_main_session_attribution(
            db_path, project_dir, session_id=session_id or ""
        )

    # Duration: query HarnessToolCallStarted event by tool_use_id
    duration_ms = None
    if tool_use_id and db_path:
        duration_ms = _compute_duration(db_path, tool_use_id)

    if not item_id:
        item_id = None

    rec = EventRecord(
        tool_name=tool_name,
        command=command,
        file_path=file_path,
        exit_code=exit_code,
        duration_ms=duration_ms,
        is_failure=is_failure,
        hook_error=str(hook_error) if hook_error else None,
        response_text=response_text,
        hook_event=hook_event,
        session_id=session_id,
        item_id=item_id,
        task_num=task_num,
        agent_type=agent_type,
        attribution_source=attribution_source,
        tool_use_id=tool_use_id,
        turn_id=turn_id,
        has_permission_decision=has_permission_decision,
    )

    # Explicit item ref extraction takes precedence over inferred attribution.
    _resolve_explicit_refs(rec, db_path)
    rec.item_id = normalize_event_item_id(rec.item_id)

    return rec

# Hard-failure indicators for ambiguous Bash PostToolUse payloads.
# These are text fragments that strongly imply a shell command failed even
# when the runtime did not emit a top-level ``error`` field or an
# ``Exit code N`` string in the response. Keep this list conservative — the
# goal is defense in depth, not to reclassify every mention of these
# phrases as a failure.
_BASH_HARD_FAILURE_INDICATORS: Tuple[str, ...] = (
    "No such file or directory",
    "command not found",
    "Permission denied",
)


def _extract_bash_command_name(command: str) -> str:
    """Return the primary executable name from a Bash command string."""
    if not command:
        return ""
    try:
        parts = shlex.split(command)
    except ValueError:
        parts = command.split()
    if not parts:
        return ""
    return os.path.basename(parts[0])


def _contains_bash_hard_failure(response_text: str, command: str) -> bool:
    """Return True for stderr-shaped Bash hard failures for this command.

    Used by :func:`parse_hook_event` as a defense-in-depth guard for
    ambiguous Bash ``PostToolUse`` payloads that lack both a top-level
    ``error`` and an ``Exit code N`` string in the response text
    .
    """
    if not response_text:
        return False
    command_name = _extract_bash_command_name(command)
    valid_prefixes = {"bash", "sh", "zsh"}
    if command_name:
        valid_prefixes.add(command_name)

    for raw_line in response_text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        prefix, sep, _rest = line.partition(":")
        if not sep or prefix not in valid_prefixes:
            continue
        if any(indicator in line for indicator in _BASH_HARD_FAILURE_INDICATORS):
            return True
    return False


def _extract_response_text(response: Any) -> str:
    """Extract text from a tool_response payload (various shapes)."""
    if isinstance(response, dict):
        content = response.get("content", "")
        if isinstance(content, list):
            return " ".join(
                str(c.get("text", "")) if isinstance(c, dict) else str(c)
                for c in content
            )[:4096]
        if isinstance(content, str):
            return content[:4096]
        return str(content)[:4096]
    if isinstance(response, str):
        return response[:4096]
    return ""
