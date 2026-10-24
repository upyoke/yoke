"""Hook stdout composition helpers for the product relay."""

from __future__ import annotations

import json
import sys

from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.hook_diagnostics import format_hook_diagnostic
from yoke_contracts.hook_context_compose import compose_context_list
from yoke_contracts.hook_runner.cursor_response import cursor_allow_stdout


HOOK_SPECIFIC_OUTPUT_KEY = "hookSpecificOutput"


def deny_stdout(reason: str, event_name: str, executor: str) -> tuple[str, int]:
    family = canonical_harness_id(executor)
    if family == "claude-code":
        return reason.strip(), 2
    if family == "cursor":
        # Cursor reads its own JSON verdict shape on exit 0; the narrative
        # travels in the message fields, never a nested envelope.
        body = {
            "permission": "deny",
            "user_message": reason,
            "agent_message": reason,
        }
        return json.dumps(body), 0
    body = {
        HOOK_SPECIFIC_OUTPUT_KEY: {
            "hookEventName": "PreToolUse"
            if event_name == "apply_patch"
            else event_name,
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }
    return json.dumps(body), 0


def write_hook_output(
    text: str, exit_code: int, executor: str, *, event_name: str = "hook evaluate"
) -> None:
    """Emit Claude blocking reasons on stderr; other wire output on stdout."""
    if not text:
        return
    if exit_code == 2 and canonical_harness_id(executor) == "claude-code":
        text = format_hook_diagnostic(event_name, text)
        sys.stderr.write(text if text.endswith("\n") else f"{text}\n")
    else:
        sys.stdout.write(text)


def _render_additional_context_envelope(
    contexts: list[str],
    event_name: str,
    *,
    cursor: bool = False,
) -> str:
    body = contexts[0] if len(contexts) == 1 else "\n\n".join(contexts)
    if cursor:
        return json.dumps({"additional_context": body})
    envelope = {
        HOOK_SPECIFIC_OUTPUT_KEY: {
            "hookEventName": event_name,
            "additionalContext": body,
        }
    }
    return json.dumps(envelope)


def _context_envelope_kind(text: str) -> tuple[str, str] | None:
    """Return ``(kind, body)`` for one context envelope, else ``None``.

    Kind is ``cursor`` or ``claude``. Merge uses the input wire shape so two
    Claude envelopes still compose when the process happens to be Cursor.
    """
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict):
        return None
    if set(parsed) == {"additional_context"}:
        body = parsed["additional_context"]
        return ("cursor", body) if isinstance(body, str) else None
    if set(parsed) != {HOOK_SPECIFIC_OUTPUT_KEY}:
        return None
    inner = parsed[HOOK_SPECIFIC_OUTPUT_KEY]
    if not isinstance(inner, dict) or "permissionDecision" in inner:
        return None
    body = inner.get("additionalContext")
    if not isinstance(body, str) or not body.strip():
        return None
    return ("claude", body)


def _merge_harness_id(*, cursor: bool, harness_id: str | None) -> str:
    if harness_id:
        return canonical_harness_id(harness_id)
    return "cursor" if cursor else "claude-code"


def merge_allow_stdout(
    first: str,
    second: str,
    event_name: str,
    *,
    cursor: bool = False,
    harness_id: str | None = None,
) -> str:
    """Merge two independently rendered allow-stdouts into one."""
    if not first:
        return second
    if not second:
        return first
    first_parts = _context_envelope_kind(first)
    second_parts = _context_envelope_kind(second)
    if first_parts is None or second_parts is None:
        if cursor:
            allow = {"permission": "allow"}
            try:
                left, right = json.loads(first), json.loads(second)
            except (ValueError, TypeError):
                pass
            else:
                if (
                    left == allow
                    and isinstance(right, dict)
                    and right.get("permission") in {"allow", "deny"}
                ):
                    return second
                if (
                    right == allow
                    and isinstance(left, dict)
                    and left.get("permission") in {"allow", "deny"}
                ):
                    return first
                if left == right == {}:
                    return first
        return f"{first}{second}"
    first_kind, first_body = first_parts
    second_kind, second_body = second_parts
    if first_kind != second_kind:
        return f"{first}{second}"
    emit_cursor = first_kind == "cursor"
    contexts = [body for body in (first_body, second_body) if body.strip()]
    if not contexts:
        return json.dumps({"additional_context": ""}) if emit_cursor else ""
    body = compose_context_list(
        contexts, harness_id=_merge_harness_id(cursor=cursor, harness_id=harness_id)
    )
    if not body:
        return json.dumps({"additional_context": ""}) if emit_cursor else ""
    return _render_additional_context_envelope(
        [body],
        event_name,
        cursor=emit_cursor,
    )


def render_context_stdout(
    context: str,
    event_name: str,
    *,
    cursor: bool = False,
) -> str:
    """Wrap plain context text in the harness additional-context envelope.

    The caller passes a plain string rather than anything typed: this
    package renders the harness wire shape and must not import the engine
    that composes the text.
    """
    if not context or not context.strip():
        return ""
    rendered = _render_additional_context_envelope(
        [context],
        event_name,
        cursor=cursor,
    )
    return cursor_allow_stdout(event_name, rendered) if cursor else rendered


__all__ = [
    "HOOK_SPECIFIC_OUTPUT_KEY",
    "merge_allow_stdout",
    "render_context_stdout",
    "write_hook_output",
    "deny_stdout",
]
