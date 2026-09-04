"""Bind registered hook guards to their human and audit check identity."""

from __future__ import annotations

import json

from yoke_contracts.hook_runner import lint_policy
from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.hooks.types import HookDecision, Outcome


def _annotate_message(message: str, check_id: str) -> tuple[str, str]:
    """Return ``(message, reason)`` with one check-id line."""
    try:
        parsed = json.loads(message)
    except (json.JSONDecodeError, TypeError):
        reason = attach_check_id(message, check_id)
        return reason, reason
    if not isinstance(parsed, dict):
        reason = attach_check_id(message, check_id)
        return reason, reason
    inner = parsed.get("hookSpecificOutput")
    if not isinstance(inner, dict):
        reason = attach_check_id(message, check_id)
        return reason, reason
    raw_reason = inner.get("permissionDecisionReason")
    if not isinstance(raw_reason, str):
        reason = attach_check_id(message, check_id)
        return reason, reason
    reason = attach_check_id(raw_reason, check_id)
    rendered = dict(parsed)
    rendered["hookSpecificOutput"] = {**inner, "permissionDecisionReason": reason}
    return json.dumps(rendered), reason


def bind(decision: HookDecision, module_id: str) -> HookDecision:
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
    message, reason = _annotate_message(decision.message, check_id)
    audit.update({"check_id": check_id, "denial_reason": reason})
    return HookDecision(
        outcome=decision.outcome,
        message=message,
        audit_fields=audit,
        block=decision.block,
        next=decision.next,
    )


__all__ = ["bind"]
