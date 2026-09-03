"""PreToolUse + orientation guard: refuse tool calls whose target paths
fall outside the session's claim-based authority.

The policy answers two questions per target, in order. First: does a
**different** live session hold the worktree lane this target is inside?
That refusal applies to every caller, including one holding no claim at
all, because a session with no stake in a lane is the shape that walks
into somebody else's. Second, and only for a caller that holds claims:
the target must land under (a) a claimed worktree, (b) any project's
control plane (repo root excluding ``.worktrees/``), or (c) the
free-path allowlist (``/tmp``, ``/var/folders/...``). A session with no
claims is otherwise unconstrained.

The same body renders as both a PreToolUse deny payload and an
orientation warning block; the orientation path uses the harness cwd
as a synthetic target. Pre-implementing-status worktree writes route
to :mod:`lint_session_cwd_pre_implementing` for the deny / warn /
suppression matrix.

Hook fails open on internal errors, audited via
``SessionCwdBindingFailOpen``.
"""

from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from typing import Any, Mapping, Optional, Sequence

from yoke_core.domain.denial_field_note_footer import append_field_note_footer
from yoke_core.domain.lint_lane_main_write_classify import (
    is_write_operation,
)
from yoke_core.domain.lint_session_cwd_control_plane import (
    ORIENTATION_HEADING,
    SCOPE_MISMATCH_TEMPLATE,
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
from yoke_core.domain.lint_session_cwd_repo_command import repo_command_block
from yoke_core.domain.lane_occupancy import LaneOccupant
from yoke_core.domain.lint_session_cwd_foreign_lane import (
    FAILURE_CLASS as FOREIGN_LANE_FAILURE_CLASS,
    build_denial_message as build_foreign_lane_message,
)
from yoke_core.domain.lint_session_cwd_identity import (
    FAILURE_CLASS as IDENTITY_FAILURE_CLASS,
    build_denial_message as build_identity_failure_message,
)
from yoke_core.domain.lint_session_cwd_status import (
    FAILURE_CLASS as PRE_IMPL_FAILURE_CLASS,
)
from yoke_core.domain.lint_session_cwd_target_extract import (
    extract_payload_command,
    extract_payload_targets,
)
from yoke_core.domain.lint_session_cwd_validate import (
    ValidationVerdict,
    validate_targets,
)
from yoke_core.domain.session_ambient_identity import (
    resolve_ambient_session_id,
    session_id_from_hook_payload,
)
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome
from yoke_contracts.hook_runner.session_cwd import (
    client_claude_job_tmp,
    client_scratch_root,
)


_ORIENTATION_EVENTS = frozenset({"SessionStart", "UserPromptSubmit"})


@dataclass(frozen=True)
class Verdict:
    """Outcome of a PreToolUse evaluation. ``allow=True`` => no deny payload.

    ``failure_class`` discriminates scope-mismatch vs.
    pre-implementing-status vs. foreign-lane; ``item_id`` /
    ``item_status`` / ``mode`` / ``suppression_attempted`` carry
    pre-implementing branch state, and ``occupant`` carries the holding
    claim for the foreign-lane branch.
    """

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


@dataclass(frozen=True)
class OrientationBlock:
    """Markdown block surfaced at the top of the orientation render."""

    heading: str
    body: str


def _open_conn():
    from yoke_core.domain import db_helpers
    return db_helpers.connect()


def evaluate_pre_tool_use(
    payload: Mapping[str, Any],
    *,
    watcher_capture_root: str = "",
    claude_job_tmp_root: str = "",
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
            reason=append_field_note_footer(
                build_identity_failure_message(), rule_id="lint-session-cwd",
            ),
            failure_class=IDENTITY_FAILURE_CLASS,
        )
    targets = extract_payload_targets(payload)
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
                read_only=not write_operation,
                command=command,
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
            allow=True, session_id=outcome.session_id,
            claims=outcome.claims, repo_roots=outcome.repo_roots,
        )

    if outcome.failure_class == PRE_IMPL_FAILURE_CLASS:
        return build_pre_implementing_verdict(outcome, payload)

    # When extract_payload_targets returned nothing, the deny is driven by
    # the harness cwd alone — but Yoke Authority authorises read-only /
    # self-orientation calls regardless of cwd. Short-circuit before
    # composing the deny payload when the command matches one.
    if not targets:
        signature = match_read_only_signature(command)
        if signature:
            emit_mismatch_allowed_read_only(
                session_id=outcome.session_id,
                read_only_signature=signature,
                claim_count=len(outcome.claims),
            )
            return Verdict(
                allow=True, session_id=outcome.session_id,
                claims=outcome.claims, repo_roots=outcome.repo_roots,
            )

    if outcome.failure_class == FOREIGN_LANE_FAILURE_CLASS and outcome.occupant:
        body = build_foreign_lane_message(
            offending_target=outcome.offending_target,
            occupant=outcome.occupant,
            payload=payload,
        )
    else:
        body = build_scope_mismatch_block(
            offending_target=outcome.offending_target,
            claims=outcome.claims,
            repo_roots=outcome.repo_roots,
            command=command,
        )
        body += repo_command_block(payload, outcome.claims) if not targets else ""
    reason = append_field_note_footer(body, rule_id="lint-session-cwd")
    return Verdict(
        allow=False,
        reason=reason,
        offending_target=outcome.offending_target,
        session_id=outcome.session_id,
        claims=outcome.claims,
        repo_roots=outcome.repo_roots,
        failure_class=outcome.failure_class,
        occupant=outcome.occupant,
    )


def evaluate_orientation(
    session: Optional[Mapping[str, Any]] = None,
    item: Optional[Mapping[str, Any]] = None,
    *,
    cwd: Optional[str] = None,
) -> Optional[OrientationBlock]:
    """Return a warning block when the orientation render's cwd is not
    covered by any of the session's claims; ``None`` when the session
    has no claims or cwd is already authorised.
    """
    actual_cwd = cwd if cwd is not None else os.getcwd()
    session_id = ""
    if session is not None:
        raw = session.get("session_id")
        if isinstance(raw, str):
            session_id = raw
    if not session_id:
        session_id = resolve_ambient_session_id() or ""
    if not session_id:
        return None
    try:
        with _open_conn() as conn:
            outcome = validate_targets(
                conn,
                session_id=session_id,
                targets=(),
                fallback_cwd=actual_cwd,
            )
    except Exception:
        return None
    if outcome.allow:
        return None
    body = build_scope_mismatch_block(
        offending_target=outcome.offending_target,
        claims=outcome.claims,
        repo_roots=outcome.repo_roots,
    )
    return OrientationBlock(heading=ORIENTATION_HEADING, body=body)


def _build_deny_response(reason: str) -> dict:
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }


def evaluate(record: HookContext) -> HookDecision:
    """Typed entry. Dispatches by ``record.event_name``."""
    payload = record.payload if isinstance(record.payload, dict) else {}
    job_dir = "" if record.remote else os.environ.get("CLAUDE_JOB_DIR", "")
    if record.event_name == "PreToolUse":
        try:
            verdict = evaluate_pre_tool_use(
                payload,
                watcher_capture_root=(
                    client_scratch_root(payload) if record.remote else ""
                ),
                claude_job_tmp_root=client_claude_job_tmp(payload, job_dir=job_dir),
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
            outcome=Outcome.DENY, message=envelope, block=True, next=Next.STOP,
            audit_fields=audit_fields,
        )
    if record.event_name in _ORIENTATION_EVENTS:
        try:
            block = evaluate_orientation(cwd=record.cwd)
        except Exception:
            return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
        if block is None:
            return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
        return HookDecision(
            outcome=Outcome.WARN,
            message=block.body,
            audit_fields={"heading": block.heading},
            next=Next.CONTINUE,
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
    cwd, sid, tool = payload.get("cwd"), payload.get("session_id"), payload.get("tool_name")
    record = HookContext(
        event_name="PreToolUse", executor_family="claude", executor_surface="claude",
        payload=payload, tool_name=tool if isinstance(tool, str) else None,
        cwd=cwd if isinstance(cwd, str) else None,
        session_id=sid if isinstance(sid, str) else None,
    )
    decision = evaluate(record)
    if decision.outcome is Outcome.DENY and decision.message:
        print(decision.message)
    return 0


__all__ = ["ORIENTATION_HEADING", "OrientationBlock", "SCOPE_MISMATCH_TEMPLATE",
           "Verdict", "build_scope_mismatch_block", "evaluate",
           "evaluate_orientation", "evaluate_pre_tool_use", "main"]


if __name__ == "__main__":  # pragma: no cover - CLI shim
    sys.exit(main())
