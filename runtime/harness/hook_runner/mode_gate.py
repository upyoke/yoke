"""Central enforcement-mode gate for the shared hook runner.

After a guard module returns its decision, the runner asks the registry
(:mod:`yoke_core.domain.lint_config`) for that guard's configured mode. A
guard that *blocks* while configured ``warn`` is downgraded here to a
non-blocking decision so the command runs, and the downgrade is recorded as a
``HarnessToolCallDenied`` row with ``outcome=warn``.

This is the single point that turns operator ``.yoke/lint-config`` policy into
behavior. It is what gives the chain's previously-knobless deniers a knob with
no per-guard edit: they keep returning their natural deny; the gate applies the
operator's warn/deny choice centrally. The domain owns the policy
(``resolve_mode`` -> a string); the harness owns this decision rewrite (the
domain layer must not import ``HookDecision``).
"""

from __future__ import annotations

from typing import Optional

from yoke_core.domain import lint_config
from yoke_contracts.hook_runner import lint_policy
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


def apply_mode(
    decision: HookDecision,
    module_id: str,
    *,
    context: Optional[HookContext] = None,
) -> HookDecision:
    """Return *decision*, downgraded to non-blocking when policy says ``warn``.

    No-op unless *decision* blocks, *module_id* is a registered guard, and its
    resolved mode is ``warn``. Protected guards never resolve to ``warn``
    without their override token, so they are never downgraded here.
    """
    if not (decision.block or decision.outcome is Outcome.DENY):
        return decision
    if not lint_config.is_registered(module_id):
        return decision
    snapshot = _policy_snapshot(context)
    if snapshot is not None:
        mode = lint_config.resolve_mode_from_snapshot(module_id, snapshot)
    elif context is None:
        mode = lint_config.resolve_mode(module_id)
    elif context.target_root:
        mode = lint_config.resolve_mode(module_id, root=context.target_root)
    else:
        return decision
    if mode != lint_config.WARN:
        return decision
    _emit_downgrade(module_id, context)
    audit = dict(decision.audit_fields or {})
    audit.update({"policy_mode": lint_config.WARN, "downgraded_from": decision.outcome.value})
    return HookDecision(
        outcome=Outcome.WARN, message="", next=Next.CONTINUE, audit_fields=audit,
    )


def _policy_snapshot(context: Optional[HookContext]) -> object | None:
    if context is None or not isinstance(context.payload, dict):
        return None
    if lint_policy.SNAPSHOT_PAYLOAD_KEY not in context.payload:
        return None
    return context.payload.get(lint_policy.SNAPSHOT_PAYLOAD_KEY)


def _emit_downgrade(module_id: str, context: Optional[HookContext]) -> None:
    """Best-effort ``HarnessToolCallDenied`` row recording the warn-downgrade."""
    try:
        from runtime.harness.hook_runner.denial import emit_denial_event
    except Exception:  # noqa: BLE001 — audit emission must never break dispatch
        return
    guard = module_id.rsplit(".", 1)[-1]
    payload = context.payload if context and isinstance(context.payload, dict) else {}
    tool_input = payload.get("tool_input") if isinstance(payload, dict) else None
    command = tool_input.get("command") if isinstance(tool_input, dict) else ""
    _s = lambda v: v if isinstance(v, str) else ""  # noqa: E731
    try:
        emit_denial_event(
            hook="lint-mode-gate",
            tool=(context.tool_name if context else "") or "Bash",
            check_id=guard,
            reason=(
                f"[outcome=warn] guard {guard} downgraded deny->warn by "
                f".yoke/lint-config policy"
            ),
            session_id=_s(context.session_id if context else ""),
            tool_use_id=_s(payload.get("tool_use_id")),
            turn_id=_s(payload.get("turn_id") or payload.get("message_id")),
            command_snippet=_s(command),
            outcome="warn",
        )
    except Exception:  # noqa: BLE001 — telemetry must never propagate
        return


__all__ = ["apply_mode"]
