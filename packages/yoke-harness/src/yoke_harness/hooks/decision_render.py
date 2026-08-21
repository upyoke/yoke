"""Hook stdout composition helpers for the product relay."""

from __future__ import annotations

import json


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


def _parse_context_envelope(text: str, *, cursor: bool = False) -> str | None:
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if cursor:
        if not isinstance(parsed, dict) or set(parsed) != {"additional_context"}:
            return None
        body = parsed["additional_context"]
        return body if isinstance(body, str) else None
    if not isinstance(parsed, dict) or set(parsed) != {HOOK_SPECIFIC_OUTPUT_KEY}:
        return None
    inner = parsed[HOOK_SPECIFIC_OUTPUT_KEY]
    if not isinstance(inner, dict) or "permissionDecision" in inner:
        return None
    body = inner.get("additionalContext")
    if not isinstance(body, str) or not body.strip():
        return None
    return body


def merge_allow_stdout(
    first: str,
    second: str,
    event_name: str,
    *,
    cursor: bool = False,
) -> str:
    """Merge two independently rendered allow-stdouts into one."""
    if not first:
        return second
    if not second:
        return first
    first_body = _parse_context_envelope(first, cursor=cursor)
    second_body = _parse_context_envelope(second, cursor=cursor)
    if first_body is not None and second_body is not None:
        contexts = [body for body in (first_body, second_body) if body.strip()]
        if not contexts:
            return json.dumps({"additional_context": ""})
        return _render_additional_context_envelope(
            contexts,
            event_name,
            cursor=cursor,
        )
    return f"{first}{second}"


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
