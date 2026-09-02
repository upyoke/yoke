"""Hook stdout composition helpers for the product relay."""

from __future__ import annotations

import json

from yoke_contracts.executor_labels import canonical_harness_id
from yoke_contracts.hook_context_compose import compose_context_list


HOOK_SPECIFIC_OUTPUT_KEY = "hookSpecificOutput"


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
        [body], event_name, cursor=emit_cursor,
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
    return _render_additional_context_envelope(
        [context],
        event_name,
        cursor=cursor,
    )


__all__ = [
    "HOOK_SPECIFIC_OUTPUT_KEY",
    "merge_allow_stdout",
    "render_context_stdout",
]
