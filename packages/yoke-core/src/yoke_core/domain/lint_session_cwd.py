"""Claim-authority hook; unexpected failures emit SessionCwdBindingFailOpen."""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from yoke_contracts.hook_runner.denial_identity import attach_check_id
from yoke_core.domain.lint_lane_main_write_classify import is_write_operation
from yoke_core.domain.lint_session_cwd_control_plane import (
    SCOPE_MISMATCH_TEMPLATE as SCOPE_MISMATCH_TEMPLATE,
    build_scope_mismatch_block,
    resolve_authority_cwd,
)
from yoke_core.domain.lint_session_cwd_emit import (
    emit_fail_open,
    emit_mismatch_allowed_read_only,
    emit_deny_and_build_audit,
)
from yoke_core.domain.lint_session_cwd_pre_implementing import (
    build_pre_implementing_verdict,
)
from yoke_core.domain.lint_session_cwd_read_only_signatures import (
    match_read_only_signature,
)
from yoke_core.domain.lane_occupancy import LaneOccupant
from yoke_core.domain.lint_session_cwd_identity import (
    FAILURE_CLASS as IDENTITY_FAILURE_CLASS,
    build_denial_message as build_identity_failure_message,
)
from yoke_core.domain.lint_session_cwd_status import (
    FAILURE_CLASS as PRE_IMPL_FAILURE_CLASS,
)
from yoke_core.domain.lint_session_cwd_target_extract import extract_payload_command
from yoke_core.domain.lint_session_cwd_denial import (
    build_denial_reason,
    CLIENT_HOME_AUTHORITY_UNAVAILABLE as CLIENT_HOME_AUTHORITY_UNAVAILABLE,
)
from yoke_core.domain.lint_payload_path_use import extract_payload_path_uses
from yoke_core.domain.lint_shell_path_use import PathRole
from yoke_core.domain.lint_session_cwd_validate import (
    ValidationVerdict,
    validate_targets,
)
from yoke_core.domain.session_ambient_identity import session_id_from_hook_payload
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_contracts.hook_runner.client_facts import yoke_source_root
from yoke_contracts.hook_runner.session_cwd import (
    client_claude_job_tmp,
    client_machine_home,
    client_scratch_root,
)


@dataclass(frozen=True)
class Verdict:
    """Outcome and refusal evidence for one PreToolUse evaluation."""

    allow: bool
    reason: str = ""
    offending_target: str = ""
    session_id: str = ""
    claims: Sequence[ClaimedWorktree] = ()
    repo_roots: Sequence[str] = ()
    failure_class: str = "scope_mismatch"
    item_id: Optional[int] = None
    item_status: Optional[str] = None
    mode: str = ""
    suppression_attempted: bool = False
    occupant: Optional[LaneOccupant] = None
    authority_reason: str = ""


def _open_conn():
    from yoke_core.domain import db_helpers

    return db_helpers.connect()


def evaluate_pre_tool_use(
    payload: Mapping[str, Any],
    *,
    watcher_capture_root: str = "",
    claude_job_tmp_root: str = "",
    machine_home: str | None = None,
) -> Verdict:
    """Return the :class:`Verdict` for a PreToolUse payload."""
    session_id = session_id_from_hook_payload(payload)
    tool_name = str(payload.get("tool_name") or payload.get("toolName") or "")
    write_operation = is_write_operation(tool_name, dict(payload))
    if not session_id and not write_operation:
        return Verdict(allow=True)
    if not session_id:
        return Verdict(
            allow=False,
            reason=attach_check_id(
                build_identity_failure_message(),
                check_id="lint-session-cwd",
            ),
            failure_class=IDENTITY_FAILURE_CLASS,
        )
    yoke_root = yoke_source_root(payload)
    path_uses = extract_payload_path_uses(payload, machine_home=machine_home)
    targets = [use.path for use in path_uses if use.role != PathRole.REMOTE]
    command = extract_payload_command(payload)
    fallback_cwd = resolve_authority_cwd(payload)

    try:
        with _open_conn() as conn:
            outcome: ValidationVerdict = validate_targets(
                conn,
                session_id=session_id,
                targets=targets,
                fallback_cwd=fallback_cwd,
                watcher_capture_root=watcher_capture_root,
                claude_job_tmp_root=claude_job_tmp_root,
                machine_home=machine_home,
                read_only=not write_operation,
                command=command,
                tool_name=tool_name,
                path_uses=path_uses,
                yoke_root=yoke_root,
            )
    except Exception as exc:
        emit_fail_open(
            session_id=session_id,
            error_class=exc.__class__.__name__,
            error_message=str(exc),
        )
        return Verdict(allow=True, session_id=session_id)

    if outcome.allow:
        return Verdict(
            allow=True,
            session_id=outcome.session_id,
            claims=outcome.claims,
            repo_roots=outcome.repo_roots,
        )

    if outcome.failure_class == PRE_IMPL_FAILURE_CLASS:
        return build_pre_implementing_verdict(outcome, payload)

    # Orientation with no operands may use its established read signature.
    if not targets:
        signature = match_read_only_signature(command)
        if signature:
            emit_mismatch_allowed_read_only(
                session_id=outcome.session_id,
                read_only_signature=signature,
                claim_count=len(outcome.claims),
            )
            return Verdict(
                allow=True,
                session_id=outcome.session_id,
                claims=outcome.claims,
                repo_roots=outcome.repo_roots,
            )

    reason, authority_reason = build_denial_reason(
        outcome,
        payload,
        has_targets=bool(targets),
        command=command,
        read_only=not write_operation,
        machine_home=machine_home,
        yoke_root=yoke_root,
    )
    return Verdict(
        allow=False,
        reason=reason,
        offending_target=outcome.offending_target,
        session_id=outcome.session_id,
        claims=outcome.claims,
        repo_roots=outcome.repo_roots,
        failure_class=outcome.failure_class,
        occupant=outcome.occupant,
        authority_reason=authority_reason,
    )


def _build_deny_response(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry; every machine-local root comes from a client fact."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    if record.event_name == "PreToolUse":
        try:
            verdict = evaluate_pre_tool_use(
                payload,
                watcher_capture_root=client_scratch_root(payload),
                claude_job_tmp_root=client_claude_job_tmp(payload),
                machine_home=client_machine_home(payload),
            )
        except Exception as exc:
            emit_fail_open(
                session_id=str(payload.get("session_id") or ""),
                error_class=exc.__class__.__name__,
                error_message=str(exc),
            )
            return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
        if verdict.allow:
            return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
        envelope = json.dumps(_build_deny_response(verdict.reason))
        audit_fields = emit_deny_and_build_audit(verdict)
        return HookDecision(
            outcome=Outcome.DENY,
            message=envelope,
            block=True,
            next=Next.STOP,
            audit_fields=audit_fields,
        )
    return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)


def main() -> int:
    """CLI entry: stdin -> PreToolUse evaluate -> emit deny envelope on deny."""
    try:
        payload = json.loads(sys.stdin.read() or "")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    cwd, sid, tool = (
        payload.get("cwd"),
        payload.get("session_id"),
        payload.get("tool_name"),
    )
    record = HookContext(
        event_name="PreToolUse",
        executor_family="claude",
        executor_surface="claude",
        payload=payload,
        tool_name=tool if isinstance(tool, str) else None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None,
    )
    decision = evaluate(record)
    if decision.outcome is Outcome.DENY and decision.message:
        print(decision.message)
    return 0


__all__ = [
    "SCOPE_MISMATCH_TEMPLATE",
    "Verdict",
    "build_scope_mismatch_block",
    "evaluate",
    "evaluate_pre_tool_use",
    "main",
]

if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
