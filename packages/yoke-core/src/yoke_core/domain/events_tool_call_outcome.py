"""Tool-call outcome classifier for observe / dispatcher / sweep emitters.

This module owns the tool-call outcome enum and the single classifier
function. All event emitters that record a tool-call result import these
constants and call ``classify_tool_call_outcome`` so the
``event_outcome`` and ``exit_code`` columns on ``events`` carry one
consistent vocabulary.

Two distinct subsets live here:

Core classifier outcomes (emitted by ``classify_tool_call_outcome``):

* ``completed`` — clean success, exit_code 0 (or absent).
* ``failed`` — the tool reported failure (non-zero exit, error field,
  defense-in-depth reclassification).
* ``denied`` — a permission/policy decision blocked the call.
* ``interrupted`` — orphaned start sentinel-completed at session end.
* ``structured_exit`` — preserves the existing ``observe_event_emission``
  reshape that fires when ``structured_exit`` is in anomalies (e.g.
  ``Awaiting human approval``). This is a first-class outcome, not a
  variant of completed/failed, because downstream audit queries treat
  approval-gate exits as a distinct lifecycle event from real failures.

Event-class-conditional outcomes (recorded only on ``HarnessToolCallDenied``
by the hook runner's ``yoke_core.hooks.guard_denial_record``, never by the
classifier):

* ``warn`` — warn-mode lint hit. The guardrail recorded an audit row but
  did not block. CLAUDE.md ``## Command Output — Hard Rule`` documents
  this as required audit-trail behavior.
* ``suppression_attempted`` — operator placed a ``# lint:no-*-check``
  suppression token on the command body. The token is honoured ONLY as
  audit evidence so reviewers can grep bypass attempts. ``.yoke/docs/agents/rules/lanes-and-claims.md`` documents
  the symmetry.

The classifier is a pure function: no I/O, no DB, no side effects. Neither
``warn`` nor ``suppression_attempted`` is in ``FAILED_OUTCOMES`` — they
are audit signals, not real denials, so ``events list --failed-only``
must not sweep them in.
"""

from __future__ import annotations

from typing import Optional, Tuple

from yoke_core.domain.observe_parsing import EventRecord

# Canonical classifier outcome vocabulary.
OUTCOME_COMPLETED: str = "completed"
OUTCOME_FAILED: str = "failed"
OUTCOME_DENIED: str = "denied"
OUTCOME_INTERRUPTED: str = "interrupted"
OUTCOME_STRUCTURED_EXIT: str = "structured_exit"

# Event-class-conditional outcomes the hook runner records on
# HarnessToolCallDenied. Not produced by classify_tool_call_outcome.
OUTCOME_WARN: str = "warn"
OUTCOME_SUPPRESSION_ATTEMPTED: str = "suppression_attempted"

OUTCOMES: frozenset[str] = frozenset(
    {
        OUTCOME_COMPLETED,
        OUTCOME_FAILED,
        OUTCOME_DENIED,
        OUTCOME_INTERRUPTED,
        OUTCOME_STRUCTURED_EXIT,
        OUTCOME_WARN,
        OUTCOME_SUPPRESSION_ATTEMPTED,
    }
)


def classify_tool_call_outcome(rec: EventRecord) -> Tuple[str, Optional[int]]:
    """Return ``(event_outcome, exit_code)`` for a parsed tool-call record.

    Truth table (first match wins):

    1. ``has_permission_decision and is_failure`` -> ``(denied, exit_code)``.
       Permission/policy denial — the harness refused to execute.
    2. ``structured_exit in anomalies`` -> ``(structured_exit, exit_code)``.
       Preserves the existing observe_event_emission reshape for
       approval-gate exits.
    3. ``is_failure`` -> ``(failed, exit_code)``.
       The parser already classified this as a failure (top-level error,
       defense-in-depth hard-failure text, Codex transcript reconcile).
    4. ``exit_code is not None and exit_code > 0`` -> ``(failed, exit_code)``.
       Defense in depth: a parsed nonzero exit that somehow escaped the
       upstream ``is_failure`` flip still records the truth.
    5. otherwise -> ``(completed, exit_code or 0)``.

    The returned outcome is always a member of :data:`OUTCOMES`.
    """
    if rec.has_permission_decision and rec.is_failure:
        return OUTCOME_DENIED, rec.exit_code

    if "structured_exit" in rec.anomalies:
        return OUTCOME_STRUCTURED_EXIT, rec.exit_code

    if rec.is_failure:
        return OUTCOME_FAILED, rec.exit_code

    if rec.exit_code is not None and rec.exit_code > 0:
        return OUTCOME_FAILED, rec.exit_code

    return OUTCOME_COMPLETED, rec.exit_code if rec.exit_code is not None else 0


__all__ = [
    "OUTCOME_COMPLETED",
    "OUTCOME_FAILED",
    "OUTCOME_DENIED",
    "OUTCOME_INTERRUPTED",
    "OUTCOME_STRUCTURED_EXIT",
    "OUTCOME_WARN",
    "OUTCOME_SUPPRESSION_ATTEMPTED",
    "OUTCOMES",
    "classify_tool_call_outcome",
]
