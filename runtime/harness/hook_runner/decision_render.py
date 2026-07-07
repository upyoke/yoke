"""Harness-shaped decision rendering for the shared hook runner.

`render_claude_decision` and `render_codex_decision` aggregate a list of
``HookDecision`` records and produce a `(stdout_text, exit_code)` pair the
adapter writes to the harness's wire format. Both renderers honor the same
aggregation rule:

- If any decision is ``deny`` (``outcome=Outcome.DENY`` or ``block=True``),
  render the deny envelope for the harness, with the concatenated narrative.
  Any ``audit_fields["additionalContext"]`` advisory carried on a sibling
  non-deny decision is intentionally dropped: deny text cannot be hidden
  or replaced by advisory text.
- Otherwise, if one or more decisions carry a non-empty
  ``audit_fields["additionalContext"]``, render the
  ``hookSpecificOutput.additionalContext`` envelope. Both harnesses already
  accept this wire shape (the same envelope each hint module's subprocess
  ``__main__`` fallback emits). Multiple advisories join with a blank line
  between them, preserving chain order.
- Otherwise (warn / audit-only / suppression-attempted / allow / noop with
  no advisory), render an empty allow — the harness allows the underlying
  tool call.

For the Claude harness, deny is signaled by exit code 2 with the narrative
on stdout (Claude's documented PreToolUse blocking shape). Allow is exit 0
with empty stdout. Allow-with-context is exit 0 with the
``hookSpecificOutput.additionalContext`` JSON envelope on stdout.

For the Codex harness, deny is signaled by writing the
``hookSpecificOutput`` JSON envelope (``permissionDecision: deny``) to
stdout with exit 0 — Codex reads the JSON, not the exit code, on
PreToolUse / apply_patch events. Allow is empty stdout, exit 0.
Allow-with-context emits the same
``hookSpecificOutput.additionalContext`` envelope Claude does.

The Codex envelope shape (``hookSpecificOutput`` with
``permissionDecision: deny``) is the wire format the Codex adapter
consumes; this module is the single source of that shape across both
harnesses.
"""

from __future__ import annotations

import json
from typing import Iterable

from runtime.harness.hook_runner.types import HookDecision, Outcome


__all__ = [
    "HOOK_SPECIFIC_OUTPUT_KEY",
    "merge_allow_stdout",
    "render_claude_decision",
    "render_codex_decision",
]


# Wire-format key both harnesses consume. Codex deny envelopes,
# Codex allow-with-context envelopes, and Claude allow-with-context
# envelopes all nest their payload under this single top-level key, so
# every renderer + every test grounds its assertions on this constant.
HOOK_SPECIFIC_OUTPUT_KEY: str = "hookSpecificOutput"


def _collect_deny_narratives(decisions: Iterable[HookDecision]) -> list[str]:
    """Return non-empty narratives from every decision that asks to deny."""
    narratives: list[str] = []
    for decision in decisions:
        if decision.outcome is Outcome.DENY or decision.block:
            message = (decision.message or "").strip()
            if message:
                narratives.append(message)
    return narratives


def _collect_additional_contexts(decisions: Iterable[HookDecision]) -> list[str]:
    """Return non-empty ``additionalContext`` strings from non-deny decisions.

    Deny decisions are skipped: mixing advisory text with a deny risks
    obscuring the structural deny narrative, so the renderer drops the
    advisory and lets the deny envelope speak alone.
    """
    contexts: list[str] = []
    for decision in decisions:
        if decision.outcome is Outcome.DENY or decision.block:
            continue
        value = decision.audit_fields.get("additionalContext")
        if isinstance(value, str) and value.strip():
            contexts.append(value)
    return contexts


def _join_narratives(narratives: list[str]) -> str:
    """Join multiple deny narratives into a single operator-facing string."""
    if not narratives:
        return ""
    if len(narratives) == 1:
        return narratives[0]
    return "\n\n".join(narratives)


def _render_additional_context_envelope(
    contexts: list[str], event_name: str,
) -> str:
    """Render the ``hookSpecificOutput.additionalContext`` JSON envelope.

    Both harnesses accept this shape; ``event_name`` passes through as the
    declared ``hookEventName`` so the wire-format consumer can route by
    event. The advisory body joins multi-entry context lists with a blank
    line between them, preserving chain order.
    """
    body = contexts[0] if len(contexts) == 1 else "\n\n".join(contexts)
    envelope = {
        HOOK_SPECIFIC_OUTPUT_KEY: {
            "hookEventName": event_name,
            "additionalContext": body,
        }
    }
    return json.dumps(envelope)


def render_claude_decision(
    decisions: list[HookDecision],
    event_name: str,
) -> tuple[str, int]:
    """Render decisions into Claude Code's hook stdout/exit-code shape.

    Three outcomes:

    * Deny present → ``(<narrative>, 2)`` (Claude's blocking shape).
    * No deny + at least one non-empty advisory → the
      ``hookSpecificOutput.additionalContext`` envelope on stdout, exit 0.
    * Otherwise → ``("", 0)`` (plain allow).

    Advisory text is intentionally dropped when a deny exists so the deny
    narrative cannot be hidden or replaced.
    """
    narratives = _collect_deny_narratives(decisions)
    if narratives:
        return (_join_narratives(narratives), 2)
    contexts = _collect_additional_contexts(decisions)
    if contexts:
        return (_render_additional_context_envelope(contexts, event_name), 0)
    return ("", 0)


def render_codex_decision(
    decisions: list[HookDecision],
    event_name: str,
) -> tuple[str, int]:
    """Render decisions into Codex's hook stdout/exit-code shape.

    Three outcomes:

    * Deny present → the ``permissionDecision: deny`` envelope on stdout,
      exit 0. Codex reads the JSON, not the exit code, on PreToolUse /
      apply_patch events; ``apply_patch`` denies declare
      ``hookEventName: "PreToolUse"`` in the envelope (Codex's wire-format
      expectation).
    * No deny + at least one non-empty advisory → the
      ``hookSpecificOutput.additionalContext`` envelope on stdout, exit 0
      (same shape both harnesses accept; ``event_name`` passes through as
      ``hookEventName``).
    * Otherwise → ``("", 0)`` (plain allow).

    Advisory text is intentionally dropped when a deny exists so the deny
    narrative cannot be hidden or replaced.
    """
    narratives = _collect_deny_narratives(decisions)
    if narratives:
        envelope = {
            HOOK_SPECIFIC_OUTPUT_KEY: {
                "hookEventName": _codex_hook_event_name(event_name),
                "permissionDecision": "deny",
                "permissionDecisionReason": _join_narratives(narratives),
            }
        }
        return (json.dumps(envelope), 0)
    contexts = _collect_additional_contexts(decisions)
    if contexts:
        return (_render_additional_context_envelope(contexts, event_name), 0)
    return ("", 0)


def _parse_context_envelope(text: str) -> str | None:
    """Return the advisory body when *text* is exactly one context envelope."""
    try:
        parsed = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        return None
    if not isinstance(parsed, dict) or set(parsed) != {HOOK_SPECIFIC_OUTPUT_KEY}:
        return None
    inner = parsed[HOOK_SPECIFIC_OUTPUT_KEY]
    if not isinstance(inner, dict) or "permissionDecision" in inner:
        return None
    body = inner.get("additionalContext")
    if not isinstance(body, str) or not body.strip():
        return None
    return body


def merge_allow_stdout(first: str, second: str, event_name: str) -> str:
    """Merge two independently rendered allow-stdouts into one.

    The https relay split renders each half's decisions separately; this
    rejoins them for the harness. When both halves are single
    ``additionalContext`` envelopes, their bodies join into ONE envelope
    (blank line between, *first* leading) — the same shape the in-chain
    renderer produces for sibling advisories. Any other non-empty pair
    concatenates raw, exactly like ``run_event``'s own rendered-text +
    extra-subprocess-stdout join.
    """
    if not first:
        return second
    if not second:
        return first
    first_body = _parse_context_envelope(first)
    second_body = _parse_context_envelope(second)
    if first_body is not None and second_body is not None:
        return _render_additional_context_envelope(
            [first_body, second_body], event_name,
        )
    return f"{first}{second}"


def _codex_hook_event_name(event_name: str) -> str:
    """Map runner-side event names to Codex's wire-format event names.

    Codex `apply_patch` denies travel under the ``PreToolUse`` envelope;
    every other event name passes through.
    """
    if event_name == "apply_patch":
        return "PreToolUse"
    return event_name
