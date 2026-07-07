"""Shared hook-runner dispatch core.

``run_event`` parses the hook payload, builds a ``HookContext``, resolves the
registered policy chain, dispatches typed or subprocess modules, renders the
harness-specific decision, and emits best-effort telemetry. Typed modules run
under :mod:`runtime.harness.hook_runner.typed_dispatch`'s watchdog; subprocess
modules use ``subprocess.run(timeout=...)``.

Two budgets apply: the legacy per-module ceiling
``hook_runner_module_timeout_ms`` and the total harness-wait deadline
``hook_runner_total_timeout_ms``. A deny computed before the total deadline is
rendered; unfinished ordinary work after the deadline degrades to allow/no-op.
``dry_run=True`` prints the resolved chain without invoking policy code.
Both halves of the https relay split pass ``controls``
(:class:`runtime.harness.hook_runner.remote_policy.RunControls`): the server
(``/v1/hooks/evaluate``) injects the propagated budget and skips classified
local-state policies; the relay client runs only that local-state subset
with ``flush_tail=False`` (the server's run owns the telemetry tail).
"""

from __future__ import annotations

import os
import time
from datetime import datetime, timezone
from typing import Any, Optional

from yoke_contracts.hook_runner.hook_ordering import matchers_for
from runtime.harness.hook_runner.adapter_capability import AdapterCapability
from runtime.harness.hook_runner.chain_registry import chain_for
from runtime.harness.hook_runner.deadline import (
    HookDeadline,
    resolve_module_timeout_ms,
    start_hook_deadline,
)
from runtime.harness.hook_runner import mode_gate as _mode_gate
from runtime.harness.hook_runner.remote_policy import RunControls
# The telemetry patch seam: the flush itself happens in run_tail, but the
# module attribute patched here is the same object run_tail resolves.
from runtime.harness.hook_runner import telemetry as _telemetry  # noqa: F401
from runtime.harness.hook_runner.subprocess_policy import run_subprocess_policy
from runtime.harness.hook_runner.target import resolve_context_target_root
from runtime.harness.hook_runner.typed_dispatch import audit_only_synthetic, dispatch_typed
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


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


def _str_or(value: Any, default: Optional[str] = None) -> Optional[str]:
    return value if isinstance(value, str) else default


def _build_context(
    *,
    event_name: str,
    capability: AdapterCapability,
    payload: dict[str, Any],
    remote: bool = False,
) -> HookContext:
    tool_input = payload.get("tool_input")
    command_body = (
        _str_or(tool_input.get("command")) if isinstance(tool_input, dict) else None
    )
    session_id = _str_or(payload.get("session_id"))
    payload_cwd = _str_or(payload.get("cwd"))
    # Remote evaluation must not adopt the SERVER process's cwd as the
    # client's: cwd stays payload-borne (possibly None) when remote.
    cwd = payload_cwd if remote else (payload_cwd or os.getcwd())
    return HookContext(
        event_name=event_name,
        executor_family=capability.family,
        executor_surface=os.environ.get("YOKE_EXECUTOR", capability.family),
        payload=payload,
        tool_name=_str_or(payload.get("tool_name")),
        command_body=command_body,
        cwd=cwd,
        target_root=resolve_context_target_root(payload, payload_cwd),
        session_id=session_id,
        item_id=None,
        now=datetime.now(timezone.utc),
        remote=remote,
    )


def _dispatch_subprocess(
    module_id: str,
    *,
    context: HookContext,
    stdin_data: str,
    timeout_ms: int,
) -> tuple[Optional[HookDecision], Optional[str], str]:
    """Run a subprocess policy via ``python3 -m <module_id>``."""
    failure, captured = run_subprocess_policy(
        module_id, context=context, stdin_data=stdin_data, timeout_ms=timeout_ms,
    )
    if failure:
        return None, failure, captured
    return audit_only_synthetic(), None, captured


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
        chain_for(event_name, matcher), event_name=event_name, capability=capability,
    )
    return _format_chain(chain, capability)


def _invoke_module(
    module_id: str,
    *,
    capability: AdapterCapability,
    context: HookContext,
    stdin_data: str,
    timeout_ms: int,
) -> tuple[HookDecision, str, Optional[str], tuple[str, dict]]:
    """Invoke one module; return decision, stdout, failure, telemetry record.

    Telemetry is NOT emitted here. A per-module DB write between guardrail
    evaluations charges its latency against the runner's total deadline and
    can starve the tail of the chain; ``run_event`` flushes the returned
    records as a single batched tail step instead.
    """
    started = time.monotonic()
    if module_id in capability.subprocess_modules:
        decision, failure, captured = _dispatch_subprocess(
            module_id, context=context, stdin_data=stdin_data,
            timeout_ms=timeout_ms,
        )
    else:
        decision, failure = dispatch_typed(
            module_id, context=context, timeout_ms=timeout_ms,
        )
        captured = ""
    duration_ms = int((time.monotonic() - started) * 1000)
    common = {
        "module": module_id,
        "hook_event": context.event_name,
        "executor": context.executor_family,
        "session_id": context.session_id or "",
        "item_id": context.item_id,
        "tool_name": context.tool_name or "",
        "duration_ms": duration_ms,
    }
    if failure is not None:
        return audit_only_synthetic(), captured, failure, (
            "failed", {**common, "failure": failure},
        )
    assert decision is not None
    return decision, captured, None, (
        "guardrail", {**common, "decision_outcome": decision.outcome.value},
    )


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
        deadline = HookDeadline(budget_ms=controls.budget_ms, started_at=time.monotonic())
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
    context = _build_context(
        event_name=event_name,
        capability=capability,
        payload=payload,
        remote=controls.remote if controls is not None else False,
    )
    started_at = time.monotonic()
    decisions: list[HookDecision] = []
    extra_stdout_parts: list[str] = []
    telem_records: list[tuple[str, dict]] = []
    timed_out = False

    for module_id in chain:
        if deadline.expired():
            timed_out = True
            break
        if controls is not None and controls.skip_module is not None:
            marker = controls.skip_module(module_id)
            if marker is not None:
                controls.degraded.append(marker)
                continue
        decision, captured, failure, record = _invoke_module(
            module_id,
            capability=capability,
            context=context,
            stdin_data=stdin_data,
            timeout_ms=deadline.child_timeout_ms(module_timeout_ms),
        )
        # Central mode gate (before the STOP check): downgrade block->noop when
        # the guard is configured warn in .yoke/lint-config.
        decision = _mode_gate.apply_mode(decision, module_id, context=context)
        decisions.append(decision)
        telem_records.append(record)
        if captured:
            extra_stdout_parts.append(captured)
        decision_stdout = decision.audit_fields.get("stdout")
        if isinstance(decision_stdout, str) and decision_stdout:
            extra_stdout_parts.append(decision_stdout)
        if failure and failure.startswith("timeout_") and deadline.expired():
            timed_out = True
            break
        if decision.next is Next.STOP:
            break
        if deadline.expired():
            timed_out = True
            break

    rendered_text, exit_code = capability.decision_renderer(decisions, event_name)
    if extra_stdout_parts:
        joined = "".join(extra_stdout_parts)
        rendered_text = f"{rendered_text}{joined}" if rendered_text else joined

    final_outcome = (
        "deny" if any(d.outcome is Outcome.DENY or d.block for d in decisions) else "allow"
    )
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
    # Batched telemetry flush + ensure-register + remote lifecycle: one
    # budget-gated tail step (the decision is already rendered, so a slow
    # or skipped tail can never suppress a deny) — see run_tail.
    from runtime.harness.hook_runner.run_tail import flush_run_tail

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
    )
    return rendered_text, exit_code
