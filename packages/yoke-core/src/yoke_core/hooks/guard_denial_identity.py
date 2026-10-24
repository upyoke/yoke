"""Bind registered hook guards to their human and audit check identity."""

from __future__ import annotations

from yoke_contracts.field_note_text import DENIAL_FOOTER
from yoke_contracts.hook_runner import lint_policy
from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_contracts.hook_runner.shell_guard_repairs import NOTHING_RAN, is_compound
from yoke_core.hooks.types import HookDecision, Outcome


def _with_denial_footer(message: str) -> str:
    """Append the field-note denial footer once, before check-id attachment."""
    if DENIAL_FOOTER in message:
        return message
    body = message.rstrip("\n")
    return f"{body}\n\n{DENIAL_FOOTER}"


def bind(decision: HookDecision, module_id: str, *, command: str = "") -> HookDecision:
    """Attach the registered guard's id to every denial boundary.

    A guard with condition-specific ids may select one through
    ``audit_fields['check_id']``. An empty or foreign id is replaced by the
    guard's primary id and retained as mismatch evidence.
    """
    if not (decision.outcome is Outcome.DENY or decision.block):
        return decision
    spec = lint_policy.spec_for(module_id)
    if spec is None:
        return decision
    audit = dict(decision.audit_fields or {})
    reported = audit.get("check_id")
    candidate = reported if isinstance(reported, str) else ""
    check_id = candidate if candidate in spec.report_check_ids else spec.check_id
    if candidate and candidate != check_id:
        audit["reported_check_id_mismatch"] = candidate
    reason = attach_check_id(_with_denial_footer(decision.message), check_id)
    if command and is_compound(command) and NOTHING_RAN not in reason:
        reason = attach_check_id(f"{reason}\n\n{NOTHING_RAN}", check_id)
    audit.update({"check_id": check_id, "denial_reason": reason})
    return HookDecision(
        outcome=decision.outcome,
        message=reason,
        audit_fields=audit,
        block=decision.block,
        next=decision.next,
    )


__all__ = ["bind"]
