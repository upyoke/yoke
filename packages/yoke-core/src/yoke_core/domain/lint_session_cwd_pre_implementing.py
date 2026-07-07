"""Pre-implementing-status branch for the session-cwd policy.

Refuse worktree-bound writes while the claim's item is in a
pre-implementing status. The validator
(:mod:`lint_session_cwd_validate`) decides whether the gate fires; this
module renders the deny / warn / suppression matrix and emits the
matching audit event. The orchestrator (:mod:`lint_session_cwd`) calls
:func:`build_pre_implementing_verdict` to produce a :class:`Verdict`
without taking on the mode parsing, message rendering, or emit
choreography itself.

Mode is pinned by machine config key ``lint_session_cwd_status_mode``;
suppression token ``# lint:no-pre-implementing-status-check`` is
recorded as audit evidence only — it does NOT unblock.
"""

from __future__ import annotations

from typing import Any, Mapping

from yoke_core.domain.lint_session_cwd_emit import (
    emit_pre_implementing_status,
)
from yoke_core.domain.lint_session_cwd_status import (
    FAILURE_CLASS,
    build_denial_message,
    command_has_suppression_token,
    read_mode,
)
from yoke_core.domain.lint_session_cwd_validate import ValidationVerdict


def _extract_bash_command(payload: Mapping[str, Any]) -> str:
    """Return the Bash command text from ``payload`` (empty when absent)."""
    tool_input = payload.get("tool_input") or payload.get("toolInput") or {}
    if not isinstance(tool_input, Mapping):
        return ""
    cmd = tool_input.get("command") or tool_input.get("cmd")
    if isinstance(cmd, str):
        return cmd
    return ""


def build_pre_implementing_verdict(
    outcome: ValidationVerdict,
    payload: Mapping[str, Any],
):
    """Resolve mode + suppression and return a :class:`Verdict`.

    Side effect: emits ``SessionCwdMismatchDenied`` carrying
    ``failure_class=pre_implementing_status`` and an ``outcome`` of
    ``warn``, ``blocked``, or ``suppression_attempted`` so reviewers can
    cleanly separate the three populations.

    The denial body is rendered by
    :func:`lint_session_cwd_status.build_denial_message` so the
    operator sees the exact denial wording. ``warn`` mode allows the call
    (no deny payload) but still records the audit event.
    """
    # Lazy import to avoid the orchestrator <-> branch circular ring.
    from yoke_core.domain.lint_session_cwd import Verdict

    mode = read_mode()
    command = _extract_bash_command(payload)
    suppressed = command_has_suppression_token(command)
    item = outcome.matched_claim
    item_id = item.item_id if item is not None else 0
    status = outcome.item_status or ""

    if mode == "warn":
        emit_pre_implementing_status(
            session_id=outcome.session_id,
            item_id=item_id,
            status=status,
            target_path=outcome.offending_target,
            mode=mode,
            outcome="warn",
        )
        return Verdict(
            allow=True,
            session_id=outcome.session_id,
            claims=outcome.claims,
            repo_roots=outcome.repo_roots,
            failure_class=FAILURE_CLASS,
            item_id=item_id,
            item_status=status,
            mode=mode,
        )

    audit_outcome = "suppression_attempted" if suppressed else "blocked"
    emit_pre_implementing_status(
        session_id=outcome.session_id,
        item_id=item_id,
        status=status,
        target_path=outcome.offending_target,
        mode=mode,
        outcome=audit_outcome,
    )
    return Verdict(
        allow=False,
        reason=build_denial_message(item_id, status),
        offending_target=outcome.offending_target,
        session_id=outcome.session_id,
        claims=outcome.claims,
        repo_roots=outcome.repo_roots,
        failure_class=FAILURE_CLASS,
        item_id=item_id,
        item_status=status,
        mode=mode,
        suppression_attempted=suppressed,
    )


__all__ = ["build_pre_implementing_verdict"]
