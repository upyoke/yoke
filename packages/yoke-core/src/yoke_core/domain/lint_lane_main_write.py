"""PreToolUse hook: refuse source writes to main while a lane is held.

While a session holds an implementation-lane work claim recorded in
``item_worktrees.path``, tracked source writes to the same project's
main checkout (the repo root excluding ``.worktrees/``) are refused.
Liveness is that recorded path — the same DB-authority read
``session_claimed_worktrees`` uses — not a filesystem probe on the
evaluating machine. An https control plane has no checkout, so
``Path.is_dir()`` would treat every live lane as missing and fail open.

The guard fires only on direct filesystem write shapes (Edit/Write,
shell file redirects, write-verb command bases, embedded Python
writes) — never on registered ``yoke <subcommand>`` adapters, cwd-only
relationships, or a heredoc that does not write a path. A held claim
whose recorded lane is gone from disk *and* whose claim heartbeat is
stale emits an advisory (once per session+item) and does not arm.
Reads, free-path scratch, generated-view writers, sessions with no
recorded lane, and pre-implementation authoring on main stay
unaffected.

Mode resolves from ``.yoke/lint-config`` key ``lint_lane_main_write``
(default ``deny``). Suppression token
``# lint:no-lane-main-write-check`` is audit-only. Escape token
``# lint:allow-lane-main-write`` records ``LaneMainWriteEscapeUsed``
and allows the call.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from typing import Any, Mapping

from yoke_core.domain.lint_lane_main_write_classify import (
    collect_main_write_targets,
    command_has_suppression_token,
    item_label,
    lane_equivalent_path,
    lane_path_exists_on_disk,
    payload_has_escape_token,
)
from yoke_core.domain.lint_lane_main_write_emit import (
    claim_heartbeat_is_stale,
    emit_denied,
    emit_escape_used,
    emit_stranded_lane_advisory,
    stranded_advisory_already_recorded,
)
from yoke_core.domain.lint_lane_main_write_messages import ESCAPE_TOKEN, format_denial
from yoke_core.domain.lint_session_cwd_control_plane import resolve_authority_cwd
from yoke_core.domain.lint_session_cwd_path_authority import derive_repo_roots
from yoke_core.domain.lint_session_cwd_status import is_pre_implementing_status
from yoke_core.domain.lint_session_cwd_target_extract import extract_payload_command
from yoke_core.domain.lint_session_cwd_validate import (
    _lookup_item_status,
    _lookup_item_workflow,
)
from yoke_core.domain.session_ambient_identity import session_id_from_hook_payload
from yoke_core.domain.session_claimed_worktrees import ClaimedWorktree, claimed_worktrees
from yoke_core.hooks.types import HookContext, HookDecision, Next, Outcome

CHECK_ID = "lint-lane-main-write"
GUARD_KEY = "lint_lane_main_write"
DEFAULT_MODE = "deny"
VALID_MODES = ("warn", "deny")


@dataclass(frozen=True)
class Verdict:
    allow: bool
    reason: str = ""
    attempted_path: str = ""
    lane_path: str = ""
    lane_equivalent: str = ""
    item_label: str = ""
    item_id: int = 0
    mode: str = DEFAULT_MODE
    suppression_attempted: bool = False
    escape_used: bool = False


def _open_conn():
    from yoke_core.domain import db_helpers
    return db_helpers.connect()


def _read_mode(payload: object | None = None) -> str:
    from yoke_core.domain import lint_config
    return lint_config.resolve_mode_for_payload(GUARD_KEY, payload)


def _config_note(mode: str) -> str:
    from yoke_core.domain import lint_config
    return lint_config.describe_config_source(GUARD_KEY, mode)


def _extract_tool_name(payload: Mapping[str, Any]) -> str:
    for key in ("tool_name", "toolName"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    return ""


def _extract_session_id(payload: Mapping[str, Any]) -> str:
    return session_id_from_hook_payload(payload)


def _lane_is_active(conn: Any, claim: ClaimedWorktree) -> bool:
    status = _lookup_item_status(conn, claim.item_id)
    workflow = _lookup_item_workflow(conn, claim.item_id)
    return not is_pre_implementing_status(workflow, status)


def evaluate_pre_tool_use(payload: Mapping[str, Any]) -> Verdict:
    session_id = _extract_session_id(payload)
    if not session_id:
        return Verdict(allow=True)

    tool_name = _extract_tool_name(payload)
    if not tool_name:
        return Verdict(allow=True)

    payload_dict = dict(payload)
    try:
        with _open_conn() as conn:
            claims = claimed_worktrees(conn, session_id=session_id)
            if not claims:
                return Verdict(allow=True)
            active_claims = [c for c in claims if _lane_is_active(conn, c)]
            if not active_claims:
                return Verdict(allow=True)
            repo_roots = tuple(derive_repo_roots(conn, active_claims))
            fallback_cwd = resolve_authority_cwd(payload)
            hits = collect_main_write_targets(
                tool_name=tool_name,
                payload=payload_dict,
                fallback_cwd=fallback_cwd,
                claims=tuple(active_claims),
                repo_roots=repo_roots,
            )
            if not hits:
                return Verdict(allow=True)
            attempted_path, claim = hits[0]
            if (
                not lane_path_exists_on_disk(claim)
                and claim_heartbeat_is_stale(conn, session_id, claim)
            ):
                if not stranded_advisory_already_recorded(
                    conn, session_id=session_id, item_id=claim.item_id,
                ):
                    emit_stranded_lane_advisory(
                        session_id=session_id,
                        lane_path=claim.worktree_path,
                        item_id=claim.item_id,
                        item_label=item_label(claim),
                    )
                return Verdict(allow=True)
    except Exception:
        return Verdict(allow=True)

    attempted_path, claim = hits[0]
    lane_path = claim.worktree_path
    equivalent = lane_equivalent_path(attempted_path, claim)
    label = item_label(claim)
    mode = _read_mode(payload)
    command = extract_payload_command(payload_dict)
    suppression_seen = command_has_suppression_token(command)

    if payload_has_escape_token(payload_dict):
        emit_escape_used(
            session_id=session_id,
            attempted_path=attempted_path,
            lane_path=lane_path,
            item_id=claim.item_id,
        )
        return Verdict(
            allow=True,
            attempted_path=attempted_path,
            lane_path=lane_path,
            lane_equivalent=equivalent,
            item_label=label,
            item_id=claim.item_id,
            mode=mode,
            escape_used=True,
        )

    reason = format_denial(
        item_label=label,
        lane_path=lane_path,
        attempted_path=attempted_path,
        lane_equivalent=equivalent,
        mode=mode,
        suppression_seen=suppression_seen,
        config_note=_config_note(mode),
    )
    emit_denied(
        session_id=session_id,
        attempted_path=attempted_path,
        lane_path=lane_path,
        lane_equivalent=equivalent,
        item_id=claim.item_id,
        mode=mode,
        suppression_attempted=suppression_seen,
    )

    if mode == "warn":
        return Verdict(
            allow=True,
            reason=reason,
            attempted_path=attempted_path,
            lane_path=lane_path,
            lane_equivalent=equivalent,
            item_label=label,
            item_id=claim.item_id,
            mode=mode,
            suppression_attempted=suppression_seen,
        )

    return Verdict(
        allow=False,
        reason=reason,
        attempted_path=attempted_path,
        lane_path=lane_path,
        lane_equivalent=equivalent,
        item_label=label,
        item_id=claim.item_id,
        mode=mode,
        suppression_attempted=suppression_seen,
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
    payload = record.payload if isinstance(record.payload, dict) else {}
    verdict = evaluate_pre_tool_use(payload)
    if verdict.allow:
        return HookDecision(outcome=Outcome.NOOP, next=Next.CONTINUE)
    envelope = json.dumps(_build_deny_response(verdict.reason))
    return HookDecision(
        outcome=Outcome.DENY,
        message=envelope,
        block=True,
        next=Next.STOP,
        audit_fields={
            "attempted_path": verdict.attempted_path,
            "lane_path": verdict.lane_path,
            "mode": verdict.mode,
            "suppression_attempted": verdict.suppression_attempted,
        },
    )


def main() -> int:
    try:
        payload = json.loads(sys.stdin.read() or "")
    except Exception:
        return 0
    if not isinstance(payload, dict):
        return 0
    cwd, sid, tool = payload.get("cwd"), payload.get("session_id"), payload.get("tool_name")
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
    "CHECK_ID",
    "DEFAULT_MODE",
    "ESCAPE_TOKEN",
    "GUARD_KEY",
    "VALID_MODES",
    "Verdict",
    "evaluate",
    "evaluate_pre_tool_use",
    "main",
]


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
