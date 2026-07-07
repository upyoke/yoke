"""Process-offer policy gate for ``decide_next_action``.

``/yoke do`` consults a config-backed :class:`ProcessOfferPolicy` before
dispatching a process-backed ``NextAction`` (``STRATEGIZE``, ``FEED``,
future).
Disabled processes never acquire a process work claim and never read
the process skill — the gate either swaps the action for a runnable
charge candidate (when one exists on the frontier) or rewrites the
action as a non-chainable terminal recommendation naming the direct
command and the config key that disabled autonomous dispatch.

The gate proper (:func:`apply_process_offer_gate`) is a pure function
over the already-decided ``NextAction`` and the live ``FrontierState``
plus the policy. The skip-memory recording side-effect
(:func:`record_disabled_process_skip`) is a separate helper (needs the
live read-write connection); the caller applies the gate first, then
records the skip from the resulting ``NextAction.context``.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from yoke_core.api.routing_config import ProcessOfferPolicy

from .chain_skip_memory_filter import merge_skip_memory_with_policy
from .scheduler_events import emit_scheduler_offer_skipped
from .session_contract import ActionKind, FrontierState, NextAction
from .session_decision_charge import build_charge_context
from .session_decision_lane_gate import LaneGateVerdict, evaluate_lane_gate
from .sessions_queries_chain import append_chain_skip_entry
from .work_processes import action_kind_to_process_key, process_key_to_path


def is_process_action_disabled(
    action: NextAction,
    policy: Optional[ProcessOfferPolicy],
) -> Optional[str]:
    """Return the disabled process key when ``action`` is gated by ``policy``.

    Returns ``None`` when the action is not a process action, when no
    policy is supplied, or when the policy enables the action's process
    key. The returned key is the registered ``PROCESS_*`` form so the
    caller can hand it to ``policy.config_key_for`` for telemetry.
    """
    if policy is None or action is None:
        return None
    process_key = action_kind_to_process_key(action.action.value)
    if process_key is None:
        return None
    if policy.is_enabled(process_key):
        return None
    return process_key


def _evaluate_lane_gate(
    *,
    action: NextAction,
    process_key: str,
    correlation: str,
    lane_allowed_paths: Optional[Dict[str, List[str]]],
    execution_lane: Optional[str],
) -> Optional[NextAction]:
    """Return a lane-policy WAIT when the lane allowlist excludes this process.

    Returns ``None`` when no lane policy is configured, when the
    process key has no path-token in the registry, or when the path
    is allowed for this lane.

    Unknown lanes (the lane has no entry in ``lane_allowed_paths``)
    now resolve to a ``WAIT`` with ``wait_reason='lane_policy_unknown'``
    — the lane gate closed the silent fail-open bypass that previously let
    any unknown lane skip the policy gate. The WAIT shape carries the
    unknown lane and the set of declared lanes so operators can fix
    config or caller.
    """
    required_path = process_key_to_path(process_key)
    if required_path is None:
        return None
    gate = evaluate_lane_gate(
        execution_lane=execution_lane,
        required_path=required_path,
        lane_allowed_paths=lane_allowed_paths,
    )
    if not gate.is_blocked:
        return None
    reason = (
        f"Lane '{execution_lane or 'primary'}' is not configured "
        f"to run path '{required_path}' for {process_key}."
        if gate.verdict is LaneGateVerdict.WAIT_DISALLOWED
        else (
            f"Lane '{execution_lane or 'primary'}' is unknown to lane "
            f"policy; declare lane_paths_<lane> in machine config before "
            f"routing {process_key}."
        )
    )
    ctx = gate.wait_context()
    ctx["actual_lane"] = execution_lane
    ctx["recommended_action"] = action.action.value
    ctx["process_key"] = process_key
    ctx["original_reason"] = action.reason
    ctx["original_context"] = dict(action.context or {})
    return NextAction(
        action=ActionKind.WAIT,
        reason=reason,
        chainable=False,
        correlation_id=correlation,
        context=ctx,
    )


def apply_process_offer_gate(
    action: NextAction,
    frontier: FrontierState,
    correlation: str,
    policy: Optional[ProcessOfferPolicy],
    *,
    lane_allowed_paths: Optional[Dict[str, List[str]]] = None,
    execution_lane: Optional[str] = None,
) -> NextAction:
    """Filter a process-backed ``NextAction`` through lane and policy gates.

    Returns the original action when:
      - the action is non-process (``RESUME`` / ``CHARGE`` / ``WAIT`` /
        ``ESCALATE``); or
      - lane policy permits the path AND ``policy`` is ``None`` or the
        policy enables the action's process key.

    Gate ordering: the global ``do_process_offer_*`` policy check runs
    **before** the lane allowlist. A global config disable is the
    load-bearing block: only flipping ``do_process_offer_*`` changes
    the outcome, so the operator-facing reason names that knob first.
    The lane gate fires only when the global policy
    *enables* the process but the lane allowlist excludes the path; in
    that case switching lanes (or widening the lane allowlist) is the
    actionable response.

    Policy gate (existing behavior):
      When the action's process key is disabled, regardless of the
      lane allowlist:
      - if ``frontier.runnable_items`` is non-empty, returns a
        ``CHARGE`` ``NextAction`` and records the skipped process under
        ``context['skipped_process']`` for downstream chain-skip-memory
        recording; the chain-step accounting treats this as a
        successful charge rather than a non-useful step. The charge
        context preserves the same scheduler routing fields that
        :func:`session_decision_charge.decide_charge_action` produces
        when ``frontier.scheduler_context`` is available, so
        ``/yoke do`` can dispatch via ``context.scheduler.next_step``
        on the fallback path exactly as it does on the normal charge
        path. When scheduler context is absent, the fallback emits the
        backward-compatible non-scheduler shape (selected_item set to
        the first runnable, no scheduler block); ``/yoke do``'s
        charge handler treats that shape as a contract failure and
        does not dispatch (parity with ``decide_charge_action``'s
        no-scheduler branch);
      - otherwise returns a non-chainable ``WAIT`` ``NextAction``
        carrying ``context['wait_reason'] = 'process_suppressed_no_alternative'``
        and a ``context['suppressed_process_recommendation']`` payload
        that names the recommended process, the disabling config key,
        the direct command, and the original reason / context the
        decision engine produced. The disabled process never surfaces
        as a terminal ``ESCALATE`` whose only cause is the config
        flag; the operator sees what the engine wanted to do as
        informational context attached to a non-process action.
        Drift-review provenance (``original_context['trigger'] ==
        'drift_review'``) is preserved so
        :func:`session_decision_drift.should_emit_drift_review_checkpoint`
        still advances the cursor on this path.

    Lane gate:
      - When ``lane_allowed_paths`` declares a configured allowlist for
        the offering session's lane and the action's process path is
        not in that allowlist, returns a non-chainable ``WAIT``
        ``NextAction`` with ``context['wait_reason'] = 'lane_policy_disallows_path'``.
        Reached only when the global policy enables the process.
      - Lanes missing from ``lane_allowed_paths`` (no
        ``lane_paths_<lane>`` declared) now return a ``WAIT`` with
        ``wait_reason='lane_policy_unknown'`` — the lane gate closed the
        silent fail-open bypass that let an unknown lane skip the
        policy gate entirely.
    """
    process_key = action_kind_to_process_key(action.action.value)
    if process_key is None:
        return action

    policy_disabled = policy is not None and not policy.is_enabled(process_key)

    if not policy_disabled:
        # Lane gate fires only when the global policy enables the
        # process; a globally-disabled process cannot be unblocked
        # by lane changes, so naming the lane first would mislead.
        lane_block = _evaluate_lane_gate(
            action=action,
            process_key=process_key,
            correlation=correlation,
            lane_allowed_paths=lane_allowed_paths,
            execution_lane=execution_lane,
        )
        if lane_block is not None:
            return lane_block
        # Both gates pass (or policy is None and lane permits), so proceed.
        return action

    # Policy disabled: surface the load-bearing config key + source
    # (the project capability or no-project machine config).
    assert policy is not None  # guarded by policy_disabled
    _, config_key, config_source = policy.decision_for(process_key)
    direct_command = f"/yoke {process_key.lower()}"
    skip_context: Dict[str, Any] = {
        "process_key": process_key,
        "config_key": config_key,
        "config_source": config_source,
        "recommended_action": action.action.value,
        "skip_reason": "process_disabled_by_config",
        "original_reason": action.reason,
        "direct_command": direct_command,
    }

    if frontier.runnable_items:
        if frontier.scheduler_context and frontier.selected_item:
            charge_ctx = build_charge_context(frontier)
            charge_ctx["skipped_process"] = dict(skip_context)
            selected = frontier.selected_item
        else:
            selected = frontier.runnable_items[0]
            charge_ctx = {
                "selected_item": selected,
                "runnable_items": list(frontier.runnable_items),
                "skipped_process": dict(skip_context),
            }
        return NextAction(
            action=ActionKind.CHARGE,
            reason=(
                f"{process_key} recommended but disabled by {config_key} "
                f"({config_source}); "
                f"{len(frontier.runnable_items)} runnable item(s) available — "
                f"selecting {selected}."
            ),
            chainable=True,
            correlation_id=correlation,
            context=charge_ctx,
        )

    suppressed: Dict[str, Any] = {
        "process_key": process_key,
        "config_key": config_key,
        "config_source": config_source,
        "recommended_action": action.action.value,
        "direct_command": direct_command,
        "skip_reason": "process_disabled_by_config",
        "original_reason": action.reason,
        "original_context": dict(action.context or {}),
    }
    wait_ctx: Dict[str, Any] = {
        "wait_reason": "process_suppressed_no_alternative",
        "suppressed_process_recommendation": suppressed,
    }
    return NextAction(
        action=ActionKind.WAIT,
        reason=(
            f"{process_key} recommended but disabled by {config_key}=false "
            f"({config_source}); no alternative work on the frontier. Run "
            f"{direct_command} directly to materialize work, or flip "
            f"{config_key}=true in {config_source}."
        ),
        chainable=False,
        correlation_id=correlation,
        context=wait_ctx,
    )


def _extract_skip_context(action: NextAction) -> Optional[Dict[str, Any]]:
    """Return the disabled-process skip payload from a gate-rewritten action.

    The gate writes the skip context under one of two shapes:
    ``context['skipped_process']`` (CHARGE swap path), or
    ``context['suppressed_process_recommendation']`` (suppressed-WAIT
    no-runnable path). This helper unifies them into one dict so the
    recording call site doesn't have to branch on the rewrite shape.
    """
    ctx = action.context or {}
    nested = ctx.get("skipped_process")
    if isinstance(nested, dict) and nested.get("process_key"):
        return dict(nested)
    nested_wait = ctx.get("suppressed_process_recommendation")
    if isinstance(nested_wait, dict) and nested_wait.get("process_key"):
        return dict(nested_wait)
    return None


def record_disabled_process_skip(
    conn: Any,
    *,
    session_id: str,
    chain_step: int,
    project: str,
    action: NextAction,
) -> bool:
    """Append a chain-skip-memory entry + emit ``SchedulerOfferSkipped``.

    Inspects ``action.context`` for the disabled-process skip payload
    written by :func:`apply_process_offer_gate`. When present, persists
    one entry under the session's ``chain_skip_memory`` (so the next
    offer in the same chain dedupes the disabled process) and emits
    one ``SchedulerOfferSkipped`` audit event with
    ``skip_reason='process_disabled_by_config'`` plus the canonical
    holder-equivalent context for processes (``process_key``,
    ``config_key``, ``recommended_action``, ``chain_step``).

    Returns ``True`` when an entry was recorded; ``False`` when the
    action did not carry a disabled-process payload (no-op for normal
    actions).
    """
    payload = _extract_skip_context(action)
    if payload is None:
        return False
    process_key = payload.get("process_key")
    if not process_key:
        return False
    entry: Dict[str, Any] = {
        "process_key": process_key,
        "skip_reason": "process_disabled_by_config",
        "chain_step": chain_step,
    }
    if payload.get("config_key"):
        entry["config_key"] = payload["config_key"]
    if payload.get("recommended_action"):
        entry["recommended_action"] = payload["recommended_action"]
    if payload.get("direct_command"):
        entry["direct_command"] = payload["direct_command"]
    append_chain_skip_entry(conn, session_id, entry)
    emit_scheduler_offer_skipped(
        session_id=session_id,
        skip_reason="process_disabled_by_config",
        chain_step=chain_step,
        project=project,
        process_key=process_key,
        config_key=payload.get("config_key"),
        recommended_action=payload.get("recommended_action"),
    )
    return True


__all__ = [
    "apply_process_offer_gate",
    "is_process_action_disabled",
    "merge_skip_memory_with_policy",
    "record_disabled_process_skip",
]
