"""Event emission helpers for the session-cwd binding policy.

Both events (``SessionCwdMismatchDenied``, ``SessionCwdBindingFailOpen``,
and the doctor-side ``SessionCwdBindingHealthCheckFailed``) flow through
:mod:`yoke_core.domain.emit_event`. Kept in a sibling module so the
policy entry-point and the doctor health check can both import a
single, narrow surface without copy-pasting the emit boilerplate.

Every emitter is fire-and-forget — failures are swallowed. Lifecycle
events that fail to land never block tool calls. The lint hook fails
open on any internal error; the audit trail is best-effort.
"""

from __future__ import annotations

import json
import sys


def _emit(
    name: str,
    outcome: str,
    context: dict,
    *,
    session_id: str = "",
    severity: str = "WARN",
) -> None:
    """Run ``emit_event`` with the canonical session-cwd shape.

    Each event lands as ``event_kind=lifecycle, event_type=session_cwd``
    with ``severity`` defaulting to ``WARN``. Allow-path emits override
    to ``INFO`` (the call passed; it's not a warning). Each name has a row
    in :mod:`yoke_core.domain.event_catalog`.
    """
    try:
        from yoke_core.domain import emit_event as emit_event_cli

        parser = emit_event_cli.build_parser()
        args = parser.parse_args(
            [
                "--name",
                name,
                "--kind",
                "lifecycle",
                "--type",
                "session_cwd",
                "--source-type",
                "hook",
                "--severity",
                severity,
                "--outcome",
                outcome,
                "--context",
                json.dumps(context, separators=(",", ":")),
                *(["--session-id", session_id] if session_id else []),
            ]
        )
        emit_event_cli.emit(args)
    except Exception:
        pass


def emit_mismatch_denied(
    session_id: str,
    offending_target: str,
    claim_count: int,
    authority_reason: str = "",
) -> None:
    """Emit ``SessionCwdMismatchDenied`` for a deny verdict.

    The legacy ``expected_worktree_path`` / ``actual_cwd`` / ``mode``
    fields are gone — there is no single bound worktree under the
    claim-based authority. The denied target is named directly, and
    ``claim_count`` records how many claimed worktrees the session
    held at the time of the block so post-hoc analysis can spot
    multi-claim sessions where the lint surfaced a misrouted target.
    ``authority_reason`` is a fixed classification tag and carries no file contents.
    """
    context = {
        "session_id": session_id,
        "offending_target": offending_target,
        "claim_count": int(claim_count),
    }
    if authority_reason:
        context["authority_reason"] = authority_reason
    _emit(
        name="SessionCwdMismatchDenied",
        outcome="blocked",
        context=context,
        session_id=session_id,
    )


def emit_mismatch_allowed_read_only(
    session_id: str,
    read_only_signature: str,
    claim_count: int,
) -> None:
    """Emit ``SessionCwdMismatchAllowedReadOnly`` for the allow short-circuit.

    Mirrors :func:`emit_mismatch_denied` but lands at ``severity=INFO``
    and adds a ``read_only_signature`` field naming which classifier
    pattern matched. The empty-target denial bucket can be split into
    allow-vs-deny populations with a single ``events`` query that filters
    by event-name.
    """
    context = {
        "session_id": session_id,
        "read_only_signature": read_only_signature,
        "claim_count": int(claim_count),
    }
    _emit(
        name="SessionCwdMismatchAllowedReadOnly",
        outcome="allowed",
        context=context,
        session_id=session_id,
        severity="INFO",
    )


def emit_foreign_lane_denied(
    session_id: str,
    offending_target: str,
    occupant_session_id: str,
    occupant_item_id: int,
    lane_path: str,
) -> None:
    """Emit ``SessionCwdForeignLaneDenied`` for a cross-session block.

    Recorded separately from a scope mismatch because the two describe
    different situations: a scope mismatch is one session outside its
    own authority, while this one names two sessions in the same lane
    and is the row an operator reads to find out who collided.
    """
    context = {
        "session_id": session_id,
        "offending_target": offending_target,
        "occupant_session_id": occupant_session_id,
        "occupant_item_id": int(occupant_item_id),
        "lane_path": lane_path,
    }
    _emit(
        name="SessionCwdForeignLaneDenied",
        outcome="warn",
        context=context,
        session_id=session_id,
    )


def emit_deny_and_build_audit(verdict: object) -> dict:
    """Emit the event a deny verdict calls for and return its audit row.

    One place decides which of the three deny classes a verdict is, so
    the hook body cannot emit the wrong event or record audit fields
    that disagree with it. Takes the verdict structurally rather than by
    type to keep the emit layer free of an import back into the policy
    module.
    """
    from yoke_core.domain.lint_session_cwd_foreign_lane import (
        FAILURE_CLASS as _FOREIGN_LANE,
    )
    from yoke_core.domain.lint_session_cwd_identity import (
        FAILURE_CLASS as _IDENTITY,
    )

    failure_class = getattr(verdict, "failure_class", "")
    occupant = getattr(verdict, "occupant", None)
    claims = getattr(verdict, "claims", ()) or ()

    if failure_class == _IDENTITY:
        from yoke_core.domain.execution_provenance import (
            collect_execution_provenance,
            format_provenance_line,
        )
        from yoke_core.domain.session_ambient_identity import (
            consult_identity_channels,
        )

        channels = consult_identity_channels()
        resolved = getattr(verdict, "session_id", "") or ""
        print(
            format_provenance_line(collect_execution_provenance()),
            file=sys.stderr,
        )
        _emit(
            name="SessionCwdMismatchDenied",
            outcome="blocked",
            context={
                "session_id": resolved,
                "offending_target": verdict.offending_target,
                "claim_count": len(claims),
                "failure_class": failure_class,
                "identity_channels": channels,
                "resolved_session_id": resolved,
            },
            session_id=resolved,
        )
    elif failure_class == _FOREIGN_LANE and occupant is not None:
        emit_foreign_lane_denied(
            session_id=verdict.session_id,
            offending_target=verdict.offending_target,
            occupant_session_id=occupant.session_id,
            occupant_item_id=occupant.item_id,
            lane_path=occupant.lane_path,
        )
    else:
        emit_mismatch_denied(
            session_id=verdict.session_id,
            offending_target=verdict.offending_target,
            claim_count=len(claims),
            authority_reason=getattr(verdict, "authority_reason", ""),
        )

    audit: dict = {
        "offending_target": verdict.offending_target,
        "claim_count": len(claims),
        "failure_class": failure_class,
    }
    authority_reason = getattr(verdict, "authority_reason", "")
    if authority_reason:
        audit["authority_reason"] = authority_reason
    if occupant is not None:
        audit["occupant_session_id"] = occupant.session_id
        audit["occupant_item_id"] = occupant.item_id
    if failure_class == _IDENTITY:
        from yoke_core.domain.session_ambient_identity import (
            consult_identity_channels as _channels,
        )

        audit["identity_channels"] = _channels()
        audit["resolved_session_id"] = getattr(verdict, "session_id", "") or ""
    return audit


def emit_fail_open(
    session_id: str = "",
    error_class: str = "",
    error_message: str = "",
) -> None:
    """Emit ``SessionCwdBindingFailOpen`` and say so on the tool call.

    The event alone is not enough. This branch runs precisely when the
    control plane could not be reached, which is also when the emit is
    least likely to land — so a guard that failed silently here left no
    trace anywhere, in the one session it had just stopped protecting.
    The stderr line is the part that cannot be lost.
    """
    context = {
        "session_id": session_id,
        "error_class": error_class,
        "error_message": error_message,
    }
    print(
        f"[yoke] session-cwd guard could not evaluate "
        f"({error_class}: {error_message}); this tool call was NOT "
        f"checked against lane ownership.",
        file=sys.stderr,
    )
    _emit(
        name="SessionCwdBindingFailOpen",
        outcome="warn",
        context=context,
        session_id=session_id,
    )


def emit_health_check_failed(
    session_id: str,
    offending_target: str,
    claim_count: int,
) -> None:
    """Emit ``SessionCwdBindingHealthCheckFailed`` for the doctor surface."""
    context = {
        "session_id": session_id,
        "offending_target": offending_target,
        "claim_count": int(claim_count),
    }
    _emit(
        name="SessionCwdBindingHealthCheckFailed",
        outcome="blocked",
        context=context,
        session_id=session_id,
    )


__all__ = [
    "emit_fail_open",
    "emit_health_check_failed",
    "emit_mismatch_allowed_read_only",
    "emit_mismatch_denied",
]
