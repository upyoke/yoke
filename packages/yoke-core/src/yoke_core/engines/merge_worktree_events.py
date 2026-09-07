"""Merge outcome recording for merge-worktree: durable receipt plus telemetry.

Every merge failure and every settling success passes through
:func:`_emit_merge_event`, so it is the one place that records the outcome
where a reader can still find it later. The durable half lands on the merged
item's own merge receipt; the event is the disposable telemetry beside it.
"""

from __future__ import annotations

import json
import subprocess
from typing import TYPE_CHECKING, Any, Optional

from yoke_core.domain.session_ambient_identity import resolve_ambient_session_id

if TYPE_CHECKING:
    from yoke_core.engines.merge_worktree_context import MergeContext

_MERGE_EVENT_SERVICE = "merge_worktree"
_MERGE_EVENT_KIND = "lifecycle"
_MERGE_EVENT_TYPE = "merge_lifecycle"
_MERGE_EVENT_SOURCE_TYPE = "system"


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw


def _print(msg: str, *, err: bool = False) -> None:
    return _parent()._print(msg, err=err)

#: What a merge outcome means for the item's stage strip. Failures record the
#: label a reader sees; a settling success clears whatever failure the last
#: attempt on that branch and target left behind.
_FAILURE_LABELS = {
    "MergeBlockedNoVerificationEvidence": "verification missing",
    "MergePullRequestCiFailed": "CI checks failed",
}
_FAILURE_EVENTS = frozenset(
    {
        *_FAILURE_LABELS,
        "MergeBranchPushFailed",
        "MergeEngineFailed",
        "MergePullRequestCreateFailed",
        "MergePullRequestMergeFailed",
        "MergeTargetPushFailed",
        "MergeTargetStale",
        "MergeVerificationFailed",
    }
)
_SETTLING_EVENTS = frozenset(
    {
        "MergeEngineSucceeded",
        "MergePullRequestCiPassed",
        "MergeVerificationPassed",
    }
)


def _failure_reason(context: dict[str, Any]) -> str:
    """The most specific detail this failure carried, for the receipt."""
    for key in ("stderr", "error_type", "extra"):
        detail = str(context.get(key) or "").strip()
        if detail:
            return detail
    exit_code = context.get("exit_code")
    return f"exit {exit_code}" if exit_code not in (None, "") else ""


def _record_merge_outcome(
    event_name: str,
    item_id: Optional[str | int],
    context: Optional[dict[str, Any]],
) -> None:
    """Record this outcome on the item's merge receipt.

    A merge that never named an item, or an outcome that is neither a failure
    nor a settling success, has nothing to record. A store that refuses is
    reported to the operator and never unwinds the merge: losing the strip's
    colour is a smaller failure than losing the merge.
    """
    if item_id in (None, "") or event_name not in (_FAILURE_EVENTS | _SETTLING_EVENTS):
        return
    body = context or {}
    branch = str(body.get("branch") or "").strip()
    target = str(body.get("target") or "").strip()
    if not (branch and target):
        return
    from yoke_core.domain import item_merge_receipts as receipts

    if event_name in _SETTLING_EVENTS:
        note = receipts.record_settlement(
            int(item_id), branch=branch, target=target,
        )
    else:
        note = receipts.record_failure(
            int(item_id),
            branch=branch,
            target=target,
            label=_FAILURE_LABELS.get(event_name, "merge failed"),
            phase=str(body.get("phase") or "").strip(),
            reason=_failure_reason(body),
        )
    if note:
        _print(note, err=True)


def _emit_telemetry(
    event_name: str,
    *,
    severity: str,
    outcome: str,
    item_id: Optional[str | int],
    context: Optional[dict[str, Any]],
) -> None:
    """Publish one merge lifecycle event.  Never raises."""
    try:
        from yoke_core.domain import emit_event as _emit_module  # local import to avoid cycles
        import argparse as _argparse

        normalized_item_id = item_id
        if isinstance(item_id, str) and item_id.isdigit():
            normalized_item_id = int(item_id)

        ns = _argparse.Namespace(
            name=event_name,
            kind=_MERGE_EVENT_KIND,
            type=_MERGE_EVENT_TYPE,
            source_type=_MERGE_EVENT_SOURCE_TYPE,
            severity=severity,
            outcome=outcome or None,
            session_id=resolve_ambient_session_id() or "",
            event_id="",
            org_id="",
            request_id="",
            actor_id=None,
            environment="",
            service=_MERGE_EVENT_SERVICE,
            project="",
            item_id=normalized_item_id if normalized_item_id is not None else "",
            task_num=None,
            agent="",
            tool_name="",
            duration_ms=None,
            exit_code=None,
            trace_id="",
            parent_id="",
            anomaly_flags="",
            tool_use_id="",
            turn_id="",
            hook_event_name="",
            context=(json.dumps(context, separators=(",", ":"), ensure_ascii=False) if context else ""),
            error_context="",
        )
        _emit_module.emit(ns)
    except Exception:
        # Telemetry failures are non-fatal.  We intentionally swallow them so
        # a misconfigured events registry or missing DB cannot break a merge.
        pass


def _emit_merge_event(
    event_name: str,
    *,
    severity: str = "INFO",
    outcome: str = "",
    item_id: Optional[str | int] = None,
    context: Optional[dict[str, Any]] = None,
) -> None:
    """Record this merge outcome, then emit its telemetry.  Never raises.

    The durable write happens first: it is the half a later reader depends
    on, and the event beside it is free to fail.
    """
    _record_merge_outcome(event_name, item_id, context)
    _emit_telemetry(
        event_name,
        severity=severity,
        outcome=outcome,
        item_id=item_id,
        context=context,
    )


def _fail_merge_rest(
    phase: str,
    *,
    ctx: Optional["MergeContext"] = None,
    event_name: str,
    error_detail: str,
    extra_detail: Optional[str] = None,
) -> int:
    """REST-call analog of :func:`_fail_merge_subprocess`.

    Prints the operator-facing failure line, emits the same shape of
    ``MergePullRequest*Failed`` event, and returns exit 1. ``error_detail``
    is the failure summary from the REST helper (typed error message or
    diagnostic). ``extra_detail`` is the call-site-specific guidance shown
    after the error.
    """
    _emit_merge_event_fn = _parent()._emit_merge_event
    _print("", err=True)
    _print(f"Error: merge phase '{phase}' failed.", err=True)
    if error_detail:
        _print(f"detail: {error_detail}", err=True)
    if extra_detail:
        _print(extra_detail, err=True)
    item_id = ctx.item_id if ctx and ctx.item_id else None
    branch = ctx.args.branch if ctx else ""
    target = ctx.args.target if ctx else ""
    _emit_merge_event_fn(
        event_name,
        severity="ERROR",
        outcome="failure",
        item_id=item_id,
        context={
            "phase": phase,
            "branch": branch,
            "target": target,
            "exit_code": 1,
            "stderr": (error_detail or "")[:1024],
            "stdout": "",
            "extra": extra_detail or "",
        },
    )
    return 1


def _fail_merge_subprocess(
    phase: str,
    result: subprocess.CompletedProcess[str],
    *,
    ctx: Optional["MergeContext"] = None,
    event_name: str,
    extra_detail: Optional[str] = None,
) -> int:
    """Print actionable stderr, emit a failure event, return exit code 1.

    Use this whenever a subprocess the merge path depends on returns non-zero
    and we want the operator to see what failed without reading engine source.
    """
    stderr = (result.stderr or "").strip()
    stdout = (result.stdout or "").strip()
    _emit_merge_event_fn = _parent()._emit_merge_event
    _print("", err=True)
    _print(f"Error: merge phase '{phase}' failed (exit {result.returncode}).", err=True)
    if stderr:
        _print(f"stderr: {stderr}", err=True)
    if stdout:
        _print(f"stdout: {stdout}", err=True)
    if extra_detail:
        _print(extra_detail, err=True)
    item_id = ctx.item_id if ctx and ctx.item_id else None
    branch = ctx.args.branch if ctx else ""
    target = ctx.args.target if ctx else ""
    _emit_merge_event_fn(
        event_name,
        severity="ERROR",
        outcome="failure",
        item_id=item_id,
        context={
            "phase": phase,
            "branch": branch,
            "target": target,
            "exit_code": result.returncode,
            "stderr": stderr[:1024],
            "stdout": stdout[:512],
            "extra": extra_detail or "",
        },
    )
    return 1
