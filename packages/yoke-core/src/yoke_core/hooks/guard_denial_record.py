"""Record each hook guard decision as at most one ``HarnessToolCallDenied`` row.

Guards never emit. They return a :class:`~yoke_core.hooks.types.HookDecision`
and the shared runner hands every decision to :func:`record_guard_decision`
after the lint-config mode gate and denial identity have run.
:func:`guard_audit_outcome` decides whether the decision records a row.
"""

from __future__ import annotations

from typing import Any

from yoke_core.domain.events_tool_call_outcome import (
    OUTCOME_DENIED,
    OUTCOME_SUPPRESSION_ATTEMPTED,
    OUTCOME_WARN,
)
from yoke_core.hooks import denial
from yoke_core.hooks.types import HookContext, HookDecision, Outcome


def guard_audit_outcome(decision: HookDecision) -> str:
    """Return the outcome a guard decision records, or ``""`` for none.

    A blocking decision is a denial, recorded ``suppression_attempted``
    when the guard saw its suppression token and still blocked. A decision
    that lets the call through records a row only when the guard declares
    ``audit_fields["audit_outcome"]``: ``suppression_attempted`` stays as
    declared; any other declaration (a lint-config downgrade by
    :mod:`yoke_core.hooks.mode_gate`, or a guard's intrinsic advisory)
    records ``warn``.
    """
    declared = (decision.audit_fields or {}).get("audit_outcome")
    if decision.outcome is Outcome.DENY or decision.block:
        if declared == OUTCOME_SUPPRESSION_ATTEMPTED:
            return OUTCOME_SUPPRESSION_ATTEMPTED
        return OUTCOME_DENIED
    if not declared:
        return ""
    if declared == OUTCOME_SUPPRESSION_ATTEMPTED:
        return OUTCOME_SUPPRESSION_ATTEMPTED
    return OUTCOME_WARN


def _text(value: Any) -> str:
    return value if isinstance(value, str) else ""


def _command_snippet(payload: dict[str, Any]) -> str:
    """The Bash command, or the file path a file tool targeted."""
    tool_input = payload.get("tool_input")
    if not isinstance(tool_input, dict):
        return ""
    return _text(tool_input.get("command")) or _text(tool_input.get("file_path"))


def _check_id(module_id: str, audit: dict[str, Any]) -> str:
    reported = _text(audit.get("check_id"))
    if reported:
        return reported
    from yoke_contracts.hook_runner import lint_policy

    spec = lint_policy.spec_for(module_id)
    return spec.check_id if spec is not None else module_id.rsplit(".", 1)[-1]


def record_guard_decision(
    decision: HookDecision,
    module_id: str,
    *,
    context: HookContext,
    revisions: dict[str, str] | None = None,
) -> None:
    """Record one guard decision as at most one ``HarnessToolCallDenied`` row.

    The row carries the final check id and reason. ``revisions`` (``client_revision``, ``server_revision``,
    ``guard_version_skew``) is the relayed evaluation's revision pair.
    """
    outcome = guard_audit_outcome(decision)
    if not outcome:
        return
    audit = decision.audit_fields or {}
    payload = context.payload if isinstance(context.payload, dict) else {}
    check_id = _check_id(module_id, audit)
    reason = (
        _text(audit.get("denial_reason"))
        or _text(audit.get("reason"))
        or _text(audit.get("note"))
        or decision.message
        or "Hook policy denied."
    )
    if audit.get("downgraded_from"):
        reason = (
            f"guard {check_id} downgraded deny->warn by .yoke/lint-config "
            f"policy: {reason}"
        )
    denial.emit_denial_event(
        hook=module_id,
        tool=context.tool_name or "",
        check_id=check_id,
        reason=reason,
        session_id=context.session_id or "",
        tool_use_id=_text(payload.get("tool_use_id")),
        turn_id=_text(payload.get("turn_id") or payload.get("message_id")),
        command_snippet=_command_snippet(payload),
        outcome=outcome,
        mode=_text(audit.get("policy_mode") or audit.get("mode")),
        agent=_text(payload.get("agent_type")),
        **(revisions or {}),
    )


__all__ = ["guard_audit_outcome", "record_guard_decision"]
