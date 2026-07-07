"""Bash file-mutation / ambiguous-shell path-claim guard.

PreToolUse policy for Bash commands. It shares target resolution with
``path_claim_pre_edit_guard`` so Bash and Edit/Write agree on
``out-of-claim`` and ``wrong-cwd`` failures, both rendered with the
canonical ``yoke claims path widen`` template. Parser-ambiguous shell idioms
fail closed unless the audit-only suppression token is present. Read-only
inspection commands are allowed so path claims do not blind agents during
orientation, refinement, or verification.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from yoke_core.domain.observe_normalization import (
    TOOL_KIND_BASH,
    ToolEventRecord,
)
from yoke_core.domain.path_claim_bash_guard_narrative import (
    ambiguous_narrative,
    format_narrative,
)
from yoke_core.domain.path_claim_bash_parser import (
    Mutation,
    SUPPRESSION_TOKEN,
    extract_mutations,
)
from yoke_core.domain.path_claim_bash_parser_planning_phase import (
    drop_planning_scratch_mutations,
)
from yoke_core.domain.path_claim_target_resolver import (
    ClaimContext,
    OUT_OF_CLAIM,
    evaluate_target,
    resolve_active_claim_for_session,
)
from runtime.harness.hook_runner.types import HookContext, HookDecision, Next, Outcome


# Verbs the parser may emit for a sentinel mutation tuple.
_AMBIGUOUS_VERB = "ambiguous"
_SUPPRESSED_VERB = "suppressed"


@dataclass
class BashGuardVerdict:
    """Outcome of :func:`evaluate` — pure dataclass, no side effects."""

    outcome: str = "allow"  # allow | deny | suppressed
    failure_mode: str = ""  # "" / out-of-claim / wrong-cwd / ambiguous
    narrative: str = ""
    bash_verb: str = ""
    target_path: str = ""
    claim_id: Optional[int] = None
    extra: Dict[str, Any] = field(default_factory=dict)


def _resolve_cwd(record: ToolEventRecord) -> tuple[str, bool]:
    """Return ``(cwd, fell_back_to_os_getcwd)``."""
    cwd = (record.cwd or "").strip()
    if cwd:
        return cwd, False
    return os.getcwd(), True


def evaluate_payload(
    payload: Dict[str, Any],
    claim: Optional[Dict[str, Any]] = None,
    *,
    conn: Optional[Any] = None,
) -> BashGuardVerdict:
    """Decide allow / deny for a Bash PreToolUse payload.

    ``payload`` may be a raw hook payload dict (``tool_input.command`` /
    ``cwd`` / ``session_id``) or a pre-built :class:`ToolEventRecord`.
    Both are accepted so adapters with different envelope shapes can
    call this directly.
    """
    record = _coerce_record(payload)
    if record is None or record.tool_kind != TOOL_KIND_BASH:
        return BashGuardVerdict(outcome="allow")

    command = record.command or ""
    if not command.strip():
        return BashGuardVerdict(outcome="allow")

    mutations: List[Mutation] = extract_mutations(command)
    if not mutations:
        return BashGuardVerdict(outcome="allow")

    # Planning-phase carve-out: drop scratch-targeting mutations when the
    # session's current item is pre-implementation. Preserves the
    # ``ambiguous`` and ``suppressed`` sentinels the suppression branch
    # below depends on.
    mutations = drop_planning_scratch_mutations(
        mutations, session_id=record.session_id, conn=conn,
    )
    if not mutations:
        return BashGuardVerdict(outcome="allow")

    # Suppression token short-circuits — we record audit evidence
    # (``outcome=suppression_attempted``) and allow. The first mutation
    # carries the sentinel.
    if mutations and mutations[0].verb == _SUPPRESSED_VERB:
        verdict = BashGuardVerdict(
            outcome="suppressed",
            failure_mode="",
            narrative=(
                f"path-claim guard suppressed via `{SUPPRESSION_TOKEN}`. "
                "Audit evidence recorded."
            ),
            bash_verb=_SUPPRESSED_VERB,
        )
        _emit_denial(record=record, verdict=verdict, conn=conn,
                     suppression=True)
        return verdict

    cwd, _ = _resolve_cwd(record)

    if claim is None:
        claim = resolve_active_claim_for_session(
            session_id=record.session_id, conn=conn,
        )

    # Ambiguous segments fail closed — even when no claim exists, the
    # operator opted into a guarded session by using a worktree-bound
    # claim DB. Without a claim, allow.
    if claim is None:
        return BashGuardVerdict(outcome="allow")

    ctx = ClaimContext.from_claim(claim)

    for mut in mutations:
        if mut.verb == _AMBIGUOUS_VERB:
            verdict = _build_ambiguous_verdict(mut, ctx)
            _emit_denial(record=record, verdict=verdict, conn=conn)
            return verdict

        failure = evaluate_target(
            target_path=mut.target_path,
            cwd=cwd,
            ctx=ctx,
            conn=conn,
        )
        if failure is None:
            continue
        verdict = BashGuardVerdict(
            outcome="deny",
            failure_mode=failure.mode,
            narrative=format_narrative(mut=mut, failure=failure, ctx=ctx),
            bash_verb=mut.verb,
            target_path=mut.target_path,
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

    return BashGuardVerdict(outcome="allow")


def _coerce_record(payload: Any) -> Optional[ToolEventRecord]:
    """Return a :class:`ToolEventRecord` from either shape."""
    if isinstance(payload, ToolEventRecord):
        return payload
    if not isinstance(payload, dict):
        return None
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    command = ""
    if isinstance(tool_input, dict):
        cmd = tool_input.get("command") or tool_input.get("cmd")
        if isinstance(cmd, str):
            command = cmd
    if not command:
        top = payload.get("command")
        if isinstance(top, str):
            command = top
    cwd = (
        str(payload.get("cwd") or "")
        or (
            str(tool_input.get("cwd") or "")
            if isinstance(tool_input, dict)
            else ""
        )
    )
    return ToolEventRecord(
        tool_kind=TOOL_KIND_BASH,
        changed_paths=[],
        command=command,
        patch_body="",
        tool_name=str(payload.get("tool_name") or "Bash"),
        session_id=str(payload.get("session_id") or ""),
        tool_use_id=payload.get("tool_use_id"),
        turn_id=payload.get("turn_id") or payload.get("message_id"),
        cwd=cwd,
        project_dir=str(payload.get("cwd") or payload.get("project_dir") or ""),
    )


def _build_ambiguous_verdict(
    mut: Mutation, ctx: ClaimContext,
) -> BashGuardVerdict:
    return BashGuardVerdict(
        outcome="deny",
        failure_mode=OUT_OF_CLAIM,  # collapse to OOC for telemetry simplicity
        narrative=ambiguous_narrative(mut=mut, ctx=ctx),
        bash_verb=mut.verb,
        target_path=mut.target_path,
        claim_id=ctx.claim_id,
        extra={"ambiguous_segment": mut.target_path},
    )


def _emit_denial(
    *,
    record: ToolEventRecord,
    verdict: BashGuardVerdict,
    conn: Optional[Any],
    suppression: bool = False,
) -> None:
    """Best-effort emit of ``PathClaimBashGuardDenied`` (never raises)."""
    try:
        from yoke_core.domain.events import emit_event as _native_emit
    except ImportError:
        return
    outcome = "suppression_attempted" if suppression else "blocked"
    try:
        _native_emit(
            "PathClaimBashGuardDenied",
            event_kind="lifecycle",
            event_type="path_claim",
            source_type="system",
            session_id=record.session_id,
            severity="WARN",
            outcome=outcome,
            project="yoke",
            context={
                "bash_verb": verdict.bash_verb,
                "target_path": verdict.target_path,
                "claim_id": verdict.claim_id,
                "failure_mode": verdict.failure_mode,
            },
            conn=conn,
        )
    except Exception:
        return


def decide_for_record(record: ToolEventRecord):
    """Pipeline adapter — see :mod:`harness_policy_pipeline`."""
    if record.tool_kind != TOOL_KIND_BASH:
        return None
    verdict = evaluate_payload(record)
    if verdict.outcome == "allow":
        return None
    from yoke_core.domain.harness_policy_pipeline import PolicyDecision

    if verdict.outcome == "suppressed":
        # Suppression should not block downstream policies — return a
        # warn so audit evidence is captured but the Bash call proceeds.
        return PolicyDecision(
            outcome="warn",
            reason=verdict.narrative,
            module=__name__,
        )
    return PolicyDecision(
        outcome="deny",
        reason=verdict.narrative,
        module=__name__,
        extra={
            "failure_mode": verdict.failure_mode,
            "bash_verb": verdict.bash_verb,
            "target_path": verdict.target_path,
            "claim_id": verdict.claim_id,
        },
    )


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry. Wraps :func:`evaluate_payload` for the PreToolUse Bash chain."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_payload(payload)
    if verdict.outcome != "deny":
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    envelope = json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": verdict.narrative,
        }
    })
    return HookDecision(
        outcome=Outcome.DENY, message=envelope, block=True, next=Next.STOP,
        audit_fields={
            "failure_mode": verdict.failure_mode,
            "bash_verb": verdict.bash_verb,
            "target_path": verdict.target_path,
            "claim_id": verdict.claim_id,
        },
    )


def main() -> int:
    """CLI entry: stdin -> evaluate -> emit deny envelope on deny."""
    try:
        payload = json.loads(sys.stdin.read() or "")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    cwd, sid = payload.get("cwd"), payload.get("session_id")
    record = HookContext(
        event_name="PreToolUse", executor_family="claude", executor_surface="claude",
        payload=payload, tool_name=str(payload.get("tool_name") or "Bash"),
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None,
    )
    decision = evaluate(record)
    if decision.outcome is Outcome.DENY and decision.message:
        print(decision.message)
    return 0


__all__ = [
    "BashGuardVerdict",
    "decide_for_record",
    "evaluate",
    "evaluate_payload",
    "main",
]


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
