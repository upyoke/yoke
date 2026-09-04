"""Shared hook-runner dispatch core.

``run_event`` parses the hook payload, builds a ``HookContext``, resolves the
registered policy chain, dispatches each module through
:mod:`yoke_core.hooks.runner_invoke`, renders the harness-specific decision,
and emits best-effort telemetry. A lifecycle event the harness delivered
twice is collapsed before dispatch by
:mod:`yoke_core.hooks.dispatch_dedup`.

Two budgets apply: the per-module ceiling ``hook_runner_module_timeout_ms``
and the total harness-wait deadline ``hook_runner_total_timeout_ms``. A deny
computed before the deadline is rendered; unfinished ordinary work after it
degrades to allow/no-op. ``dry_run=True`` prints the resolved chain without
invoking policy code. Both halves of the https relay split pass ``controls``
(:class:`yoke_core.hooks.remote_policy.RunControls`): the server injects the
propagated budget and skips classified local-state policies; the relay client
runs only that subset with ``flush_tail=False``.
"""

from __future__ import annotations

import time
from typing import Any, Optional

from yoke_contracts.hook_runner.chain_registry import chain_for
from yoke_contracts.hook_runner.failures import FAILURE_PREFIX
from yoke_contracts.hook_runner.hook_ordering import matchers_for
from yoke_core.domain.hook_runner_deadline import (
    HookDeadline,
    resolve_module_timeout_ms,
    start_hook_deadline,
)
from yoke_core.hooks import telemetry as _telemetry  # noqa: F401
from yoke_core.hooks.adapter_capability import AdapterCapability
from yoke_core.hooks import guard_denial_identity as _guard_denial_identity
from yoke_core.hooks import mode_gate as _mode_gate
from yoke_core.hooks.context import build_context
from yoke_core.hooks.dispatch_dedup import deduplicated_dispatch
from yoke_core.hooks.remote_policy import RunControls
from yoke_core.hooks.runner_invoke import invoke_module
from yoke_core.hooks.skipped_guards import record_skipped_guards
from yoke_core.hooks.types import HookDecision, Next, Outcome


__all__ = ["run_event"]
_resolve_timeout_ms = resolve_module_timeout_ms


def _resolve_matcher(event_name: str, payload: dict[str, Any]) -> Optional[str]:
    if event_name in {"PreToolUse", "PostToolUse"}:
        tool_name = payload.get("tool_name")
        if isinstance(tool_name, str) and tool_name:
            return tool_name
    if event_name == "apply_patch":
        return "apply_patch"
    return None


def _apply_omissions(
    chain: list[str],
    *,
    event_name: str,
    capability: AdapterCapability,
) -> list[str]:
    omitted: frozenset[str] = frozenset()
    if event_name == "apply_patch":
        omitted = capability.apply_patch_chain_omissions
    elif event_name == "PreToolUse":
        omitted = capability.pretool_omissions
    if not omitted:
        return chain
    return [m for m in chain if m not in omitted]


def _format_chain(chain: list[str], capability: AdapterCapability) -> str:
    if not chain:
        return ""
    lines = [
        f"{'[subproc]' if mid in capability.subprocess_modules else '[typed]'} {mid}"
        for mid in chain
    ]
    return "\n".join(lines) + "\n"


def _render_dry_run(
    event_name: str,
    matcher: Optional[str],
    capability: AdapterCapability,
) -> str:
    """Print the dry-run chain. With no resolved matcher on a tool-shaped
    event, enumerate every registered matcher so the operator sees the
    full per-tool layout.
    """
    if matcher is None and event_name in {"PreToolUse", "PostToolUse"}:
        sections: list[str] = []
        for tool in matchers_for(event_name) or []:
            chain = _apply_omissions(
                chain_for(event_name, tool),
                event_name=event_name,
                capability=capability,
            )
            body = _format_chain(chain, capability)
            if body:
                sections.append(f"# {event_name}:{tool}\n{body.rstrip()}")
        return "\n\n".join(sections) + "\n" if sections else ""
    chain = _apply_omissions(
        chain_for(event_name, matcher),
        event_name=event_name,
        capability=capability,
    )
    return _format_chain(chain, capability)


def run_event(
    event_name: str,
    *,
    capability: AdapterCapability,
    stdin_data: str,
    env: Optional[dict[str, str]] = None,  # noqa: ARG001 — reserved for future use
    dry_run: bool = False,
    controls: Optional[RunControls] = None,
) -> tuple[str, int]:
    """Dispatch one hook event. Never raises; failures degrade to audit-only.

    ``controls`` (relay-split evaluation) injects the caller's remaining
    budget, skips the classifier-excluded policies into ``controls.degraded``,
    merges ``payload_extra``, optionally suppresses the telemetry tail
    (``flush_tail=False``), and writes back ``timed_out`` / ``final_outcome``.
    """
    module_timeout_ms = _resolve_timeout_ms()
    if controls is not None and controls.budget_ms is not None:
        deadline = HookDeadline(
            budget_ms=controls.budget_ms, started_at=time.monotonic()
        )
    else:
        deadline = start_hook_deadline()
    payload = capability.payload_parser(stdin_data) if stdin_data else {}
    if not isinstance(payload, dict):
        payload = {}
    if controls is not None and controls.payload_extra:
        payload = {**payload, **controls.payload_extra}

    matcher = _resolve_matcher(event_name, payload)
    if dry_run:
        return _render_dry_run(event_name, matcher, capability), 0

    chain = _apply_omissions(
        chain_for(event_name, matcher),
        event_name=event_name,
        capability=capability,
    )
    context = build_context(
        event_name=event_name,
        capability=capability,
        payload=payload,
        remote=controls.remote if controls is not None else False,
    )
    if deduplicated_dispatch(
        event_name,
        context=context,
        stdin_data=stdin_data,
        controls=controls,
    ):
        # The harness delivered this lifecycle event twice; the first
        # dispatch already ran the chain. Render the empty (allow) decision
        # so the duplicate changes nothing.
        return capability.decision_renderer([], event_name)
    from yoke_core.hooks.run_tail import preflight_remote_registration

    registration_preflight = preflight_remote_registration(
        event_name=event_name,
        context=context,
        payload=payload,
        stdin_data=stdin_data,
        controls=controls,
        deadline=deadline,
    )
    started_at = time.monotonic()
    decisions: list[HookDecision] = []
    extra_stdout_parts: list[str] = []
    telem_records: list[tuple[str, dict]] = []
    timed_out = False
    skipped_guards: list[str] = []

    for index, module_id in enumerate(chain):
        if deadline.expired():
            timed_out = True
            skipped_guards = chain[index:]
            break
        if controls is not None and controls.skip_module is not None:
            marker = controls.skip_module(module_id)
            if marker is not None:
                controls.degraded.append(marker)
                continue
        decision, captured, failure, record = invoke_module(
            module_id,
            capability=capability,
            context=context,
            stdin_data=stdin_data,
            timeout_ms=deadline.child_timeout_ms(module_timeout_ms),
        )
        # Apply registered policy mode and denial identity before STOP.
        decision = _mode_gate.apply_mode(decision, module_id, context=context)
        decision = _guard_denial_identity.bind(decision, module_id)
        if (
            controls is not None
            and decision.outcome is Outcome.DENY
            and not controls.denial_audit
        ):
            audit = decision.audit_fields
            controls.denial_audit = {
                "hook": module_id,
                "check_id": str(audit.get("check_id") or module_id),
                "reason": str(
                    audit.get("denial_reason")
                    or decision.message
                    or audit.get("reason")
                    or "Hook policy denied."
                ),
            }
        decisions.append(decision)
        telem_records.append(record)
        if failure is not None and controls is not None:
            controls.degraded.append(f"{FAILURE_PREFIX}{module_id}:{failure}")
        if captured:
            extra_stdout_parts.append(captured)
        decision_stdout = decision.audit_fields.get("stdout")
        if isinstance(decision_stdout, str) and decision_stdout:
            extra_stdout_parts.append(decision_stdout)
        if failure and failure.startswith("timeout_") and deadline.expired():
            timed_out = True
            skipped_guards = chain[index + 1 :]
            break
        if decision.next is Next.STOP:
            break
        if deadline.expired():
            timed_out = True
            skipped_guards = chain[index + 1 :]
            break
    if skipped_guards:
        record_skipped_guards(skipped_guards, controls)

    rendered_text, exit_code = capability.decision_renderer(decisions, event_name)
    if extra_stdout_parts:
        joined = "".join(extra_stdout_parts)
        rendered_text = f"{rendered_text}{joined}" if rendered_text else joined

    from yoke_core.hooks.hook_delivery_settlement import settle_model_deliveries

    rendered_text, final_outcome = settle_model_deliveries(decisions, rendered_text)
    if timed_out and final_outcome == "allow":
        final_outcome = "timeout_allow"
    if controls is not None:
        controls.timed_out = timed_out
        controls.final_outcome = final_outcome
    hook_wait_ms = int((time.monotonic() - started_at) * 1000)
    if controls is not None and not controls.flush_tail:
        # The relay's client-side local-state subset: the server's run owns
        # the telemetry/ensure-register/lifecycle tail for the event.
        return rendered_text, exit_code
    # budget-gated tail step (the decision is already rendered, so a slow
    # or skipped tail can never suppress a deny) — see run_tail.
    from yoke_core.hooks.run_tail import flush_run_tail

    flush_run_tail(
        event_name=event_name,
        context=context,
        chain_length=len(chain),
        final_outcome=final_outcome,
        hook_wait_ms=hook_wait_ms,
        timed_out=timed_out,
        deadline=deadline,
        payload=payload,
        stdin_data=stdin_data,
        controls=controls,
        telem_records=telem_records,
        registration_preflight=registration_preflight,
    )
    return rendered_text, exit_code
