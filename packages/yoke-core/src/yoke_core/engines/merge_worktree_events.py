"""Structured lifecycle event helpers for merge-worktree."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from typing import Any, Optional

_MERGE_EVENT_SERVICE = "merge_worktree"
_MERGE_EVENT_KIND = "lifecycle"
_MERGE_EVENT_TYPE = "merge_lifecycle"
_MERGE_EVENT_SOURCE_TYPE = "system"


def _parent():
    from yoke_core.engines import merge_worktree as _mw
    return _mw


def _print(msg: str, *, err: bool = False) -> None:
    return _parent()._print(msg, err=err)

def _emit_merge_event(
    event_name: str,
    *,
    severity: str = "INFO",
    outcome: str = "",
    item_id: Optional[str] = None,
    context: Optional[dict[str, Any]] = None,
) -> None:
    """Emit a structured merge lifecycle event.  Never raises."""
    try:
        from yoke_core.domain import emit_event as _emit_module  # local import to avoid cycles
        import argparse as _argparse

        ns = _argparse.Namespace(
            name=event_name,
            kind=_MERGE_EVENT_KIND,
            type=_MERGE_EVENT_TYPE,
            source_type=_MERGE_EVENT_SOURCE_TYPE,
            severity=severity,
            outcome=outcome or None,
            session_id=os.environ.get("YOKE_SESSION_ID", "")
            or os.environ.get("CLAUDE_SESSION_ID", "")
            or os.environ.get("CODEX_THREAD_ID", ""),
            event_id="",
            user_id="",
            org_id="",
            request_id="",
            actor_id=None,
            environment="",
            service=_MERGE_EVENT_SERVICE,
            project="",
            item_id=(item_id or "") if item_id else "",
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
