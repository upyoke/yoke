"""Pre-edit / pre-write / pre-apply_patch path-claim guard.

Pure function: given a normalized :class:`ToolEventRecord` and the
active session's path claim, return ``(allow|deny, narrative)``.

The deny narrative includes the canonical ``yoke claims path widen``
template so the operator's first move is always one mechanical
remediation. Two failure modes share the deny shape:

* ``out-of-claim`` — the resolved path is not within any covered root of
  the active claim.
* ``wrong-cwd`` — the resolved path is within the claim's coverage by
  string match, but its physical location is in main's checkout (or a
  different worktree) than the worktree the claim was issued for.

Cwd resolution: prefer the hook payload's ``cwd``; fall back to
``os.getcwd()`` only when the payload omits it (a WARN telemetry event
records the fallback).

Public surface:

- :class:`Verdict` — ``outcome`` / ``failure_mode`` / ``narrative``.
- :func:`evaluate` — lane K imports this directly for the Codex
  ``apply_patch`` hook handler. Lane R consumes it via the universal
  policy pipeline (``decide_for_record``).
- :func:`decide_for_record` — :mod:`harness_policy_pipeline` adapter.
- The shared ``(target_path, cwd)`` resolver lives in
  :mod:`yoke_core.domain.path_claim_target_resolver` and is reused
  by :mod:`yoke_core.domain.path_claim_bash_guard`.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from yoke_core.domain.harness_policy_pipeline import build_tool_event_record
from yoke_core.domain.observe_normalization import (
    TOOL_KIND_APPLY_PATCH,
    TOOL_KIND_EDIT,
    TOOL_KIND_WRITE,
    ToolEventRecord,
)
from yoke_core.domain.path_claim_target_resolver import (
    ClaimContext,
    Failure,
    OUT_OF_CLAIM,
    WORKTREE_UNRESOLVED,
    WRONG_CWD,
    evaluate_target,
    resolve_active_claim_for_session,
    widen_template,
)
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


# Tool kinds this guard inspects. Bash is intentionally NOT here — see
# :mod:`path_claim_bash_guard` for the Bash-shaped policy.
_INSPECTED_KINDS = frozenset({TOOL_KIND_EDIT, TOOL_KIND_WRITE, TOOL_KIND_APPLY_PATCH})


@dataclass
class Verdict:
    """Outcome of :func:`evaluate` — pure dataclass, no side effects."""

    outcome: str = "allow"  # allow | deny
    failure_mode: str = ""  # "" / out-of-claim / wrong-cwd
    narrative: str = ""
    target_path: str = ""
    claim_id: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)


def _resolve_cwd(record: ToolEventRecord) -> tuple[str, bool]:
    """Return ``(cwd, fell_back)``.

    Prefers the record's payload cwd. Falls back to ``os.getcwd()`` only
    when the payload omits it (the caller emits a WARN event).
    """
    cwd = (record.cwd or "").strip()
    if cwd:
        return cwd, False
    return os.getcwd(), True


def evaluate_payload(
    record: ToolEventRecord,
    claim: Optional[Dict[str, Any]] = None,
    *,
    conn: Optional[Any] = None,
) -> Verdict:
    """Decide allow / deny for one Edit/Write/apply_patch record.

    ``claim`` may be passed explicitly (test injection) or resolved
    against the live DB via the session id on the record. When no
    active claim exists and the record changes paths, the verdict is
    ``allow`` — claim-coverage enforcement is opt-in via an active
    claim. The deny shape only fires when the session HAS a claim and
    the changed path falls outside it.
    """
    if record.tool_kind not in _INSPECTED_KINDS:
        return Verdict(outcome="allow")

    paths: List[str] = list(record.changed_paths or [])
    if not paths:
        return Verdict(outcome="allow")

    cwd, _ = _resolve_cwd(record)

    if claim is None:
        claim = resolve_active_claim_for_session(
            session_id=record.session_id, conn=conn,
        )
    if claim is None:
        return Verdict(outcome="allow")

    ctx = ClaimContext.from_claim(claim)

    for target_path in paths:
        failure = evaluate_target(
            target_path=target_path,
            cwd=cwd,
            ctx=ctx,
            conn=conn,
        )
        if failure is None:
            continue
        narrative = _format_narrative(
            tool_kind=record.tool_kind,
            target_path=target_path,
            failure=failure,
            ctx=ctx,
        )
        verdict = Verdict(
            outcome="deny",
            failure_mode=failure.mode,
            narrative=narrative,
            target_path=target_path,
            claim_id=ctx.claim_id,
            extra={
                "expected_worktree_path": (
                    failure.effective_worktree_path or ctx.worktree_path
                ),
                "covered_paths": list(ctx.covered_paths),
            },
        )
        _emit_denial(record=record, verdict=verdict, conn=conn)
        return verdict

    return Verdict(outcome="allow")


def _format_narrative(
    *,
    tool_kind: str,
    target_path: str,
    failure: Failure,
    ctx: ClaimContext,
) -> str:
    """Render the deny narrative for the given failure.

    Three shapes:

    * ``wrong-cwd`` — claim coverage matches by string but the physical
      path lives outside the bound worktree. Carries the
      ``yoke claims path widen`` template and names the expected worktree.
    * ``worktree-unresolved`` — claim has no worktree binding
      (``items.worktree`` is empty). Teaches the canonical
      ``worktree_preflight`` primitive, NOT claim widening.
    * ``out-of-claim`` — claim coverage misses the target. Carries the
      ``yoke claims path widen`` template.
    """
    if failure.mode == WORKTREE_UNRESOLVED:
        from yoke_core.domain.path_claim_bash_guard_narrative import (
            worktree_unresolved_narrative,
        )

        return worktree_unresolved_narrative(
            tool_kind=tool_kind, target_path=target_path, ctx=ctx,
        )
    template = widen_template(
        claim_id=ctx.claim_id, item_id=ctx.item_id, target_path=target_path,
    )
    expected_wt = failure.effective_worktree_path or ctx.worktree_path
    if failure.mode == WRONG_CWD:
        return (
            f"BLOCKED: path-claim guard ({tool_kind}).\n"
            f"  target_path:           {target_path}\n"
            f"  resolved_parent:       {failure.resolved_parent}\n"
            f"  expected_worktree:     {expected_wt}\n"
            f"  failure_mode:          wrong-cwd\n\n"
            "Wrong working tree — expected "
            f"`{expected_wt}`, got `{failure.resolved_parent}`. "
            "Relaunch Claude Code rooted at the worktree.\n\n"
            "Or widen the claim to cover this path:\n"
            f"  {template}"
        )
    # out-of-claim
    covered_preview = ", ".join(ctx.covered_paths[:3]) or "(no coverage)"
    extra_count = max(0, len(ctx.covered_paths) - 3)
    extra_str = f" (+{extra_count} more)" if extra_count else ""
    return (
        f"BLOCKED: path-claim guard ({tool_kind}).\n"
        f"  target_path:    {target_path}\n"
        f"  claim_id:       {ctx.claim_id}\n"
        f"  covered:        {covered_preview}{extra_str}\n"
        f"  failure_mode:   out-of-claim\n\n"
        "Path is outside this session's active claim coverage.\n"
        "Widen the claim's coverage:\n"
        f"  {template}"
    )


def _emit_denial(
    *,
    record: ToolEventRecord,
    verdict: Verdict,
    conn: Optional[Any],
) -> None:
    """Best-effort emit of ``PathClaimEditGuardDenied`` (never raises)."""
    try:
        from yoke_core.domain.events import emit_event as _native_emit
    except ImportError:
        return
    try:
        _native_emit(
            "PathClaimEditGuardDenied",
            event_kind="lifecycle",
            event_type="path_claim",
            source_type="system",
            session_id=record.session_id,
            severity="WARN",
            outcome="blocked",
            project="yoke",
            context={
                "tool_kind": record.tool_kind,
                "target_path": verdict.target_path,
                "claim_id": verdict.claim_id,
                "failure_mode": verdict.failure_mode,
            },
            conn=conn,
        )
    except Exception:
        return


def decide_for_record(record: ToolEventRecord):
    """Pipeline adapter — see :mod:`harness_policy_pipeline`.

    Returns a :class:`PolicyDecision` shaped object when the record
    crosses the guard's tool-kind matcher and the verdict is ``deny``;
    returns ``None`` otherwise so the pipeline treats it as allow.
    """
    if record.tool_kind not in _INSPECTED_KINDS:
        return None
    verdict = evaluate_payload(record)
    if verdict.outcome != "deny":
        return None
    from yoke_core.domain.harness_policy_pipeline import PolicyDecision

    return PolicyDecision(
        outcome="deny",
        reason=verdict.narrative,
        module=__name__,
        extra={
            "failure_mode": verdict.failure_mode,
            "target_path": verdict.target_path,
            "claim_id": verdict.claim_id,
        },
    )


def _build_deny_response(reason: str) -> Dict[str, Any]:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry. Builds a :class:`ToolEventRecord` and dispatches to
    :func:`evaluate_payload`. NOOP when the tool is not Edit/Write/apply_patch
    or no record can be built.
    """
    payload = record.payload if isinstance(record.payload, dict) else {}
    tool_input = payload.get("tool_input")
    tool_record = build_tool_event_record(
        tool_name=str(payload.get("tool_name") or ""),
        tool_input=tool_input if isinstance(tool_input, dict) else {},
        session_id=str(payload.get("session_id") or os.environ.get("YOKE_SESSION_ID") or ""),
        tool_use_id=payload.get("tool_use_id"),
        turn_id=payload.get("turn_id") or payload.get("message_id"),
        cwd=str(payload.get("cwd") or payload.get("project_dir") or ""),
        project_dir=str(payload.get("project_dir") or payload.get("cwd") or ""),
    )
    if tool_record is None:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    verdict = evaluate_payload(tool_record)
    if verdict.outcome != "deny":
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    envelope = json.dumps(_build_deny_response(verdict.narrative))
    return HookDecision(
        outcome=Outcome.DENY, message=envelope, block=True, next=Next.STOP,
        audit_fields={
            "failure_mode": verdict.failure_mode,
            "target_path": verdict.target_path,
            "claim_id": verdict.claim_id,
        },
    )


def main() -> int:
    """CLI entry: stdin -> typed evaluate -> emit deny envelope on deny."""
    try:
        payload = json.loads(sys.stdin.read() or "")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    record = HookContext(
        event_name="PreToolUse", executor_family="claude", executor_surface="claude",
        payload=payload, tool_name=str(payload.get("tool_name") or ""),
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None,
    )
    decision = evaluate(record)
    if decision.outcome is Outcome.DENY and decision.message:
        print(decision.message)
    return 0


__all__ = [
    "Verdict",
    "decide_for_record",
    "evaluate",
    "evaluate_payload",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
