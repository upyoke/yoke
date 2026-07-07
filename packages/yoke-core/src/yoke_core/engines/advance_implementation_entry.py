"""Advance — implementation-entry orchestrator.

Composes preflight gates -> ``worktree_preflight.run_preflight`` (claim
+ activation + worktree) -> ephemeral environment (capability-gated,
delegated to ``advance_implementation_environment``) -> finalize
(status flip via ``lifecycle.transition.execute``). Each phase emits an
``AdvancePhaseCompleted`` event. Idempotent re-entry against an
already-implementing item reuses claim + worktree and skips the flip.

CLI: ``python3 -m yoke_core.engines.advance_implementation_entry
--item YOK-N [--no-worktree] [--force] [--qa-bypass] [--session-id X]``.
Exit codes: 0 success, 1 sanctioned block, 2 bad input.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from yoke_core.domain import db_helpers
from yoke_core.domain.events import emit_event


PHASE_PREFLIGHT = "preflight"
PHASE_WORKTREE = "worktree"
PHASE_ENVIRONMENT = "environment"
PHASE_FINALIZE = "finalize"

RELEASE_WORKTREE_CREATE_FAILED = "worktree-create-failed"

IMPLEMENTATION_PHASE_STATUSES = frozenset({
    "implementing", "reviewing-implementation", "reviewed-implementation",
    "polishing-implementation", "implemented", "release", "done",
})


def _parse_item_id(raw: Any) -> int:
    s = str(raw).strip()
    if s.upper().startswith("YOK-"):
        s = s[4:]
    s = s.lstrip("0") or "0"
    return int(s)


def _resolve_session_id(explicit: Optional[str]) -> str:
    if explicit:
        return explicit
    from yoke_core.domain.session_ambient_identity import (
        resolve_ambient_session_id,
    )

    return resolve_ambient_session_id() or ""


def _read_item(item_id: int) -> Optional[Dict[str, Any]]:
    with db_helpers.connect() as conn:
        row = conn.execute(
            "SELECT i.id, i.type, i.status, i.title, p.slug AS project "
            "FROM items i LEFT JOIN projects p ON p.id = i.project_id "
            "WHERE i.id = %s",
            (int(item_id),),
        ).fetchone()
    if row is None:
        return None
    if hasattr(row, "keys"):
        return {k: row[k] for k in row.keys()}
    return {"id": row[0], "type": row[1], "status": row[2],
            "title": row[3], "project": row[4]}


def _record_phase(
    summary: Dict[str, Any], *, item_id: int, phase: str, outcome: str,
    duration_ms: int, session_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit ``AdvancePhaseCompleted`` and append to summary in one pass."""
    payload: Dict[str, Any] = {"phase": phase, "outcome": outcome,
                               "duration_ms": int(duration_ms)}
    if context:
        payload.update(context)
    result = emit_event(
        "AdvancePhaseCompleted",
        event_kind="workflow", event_type="advance_phase",
        session_id=session_id, item_id=str(item_id), context=payload,
    )
    if result is not None and not result.ok:
        raise RuntimeError(
            f"AdvancePhaseCompleted emission failed: {result.reason}"
        )
    summary["phases"].append({"phase": phase, "outcome": outcome,
                              "duration_ms": int(duration_ms)})


def _release_claim(item_id: int, session_id: str, reason: str) -> None:
    """Best-effort release. Never raises."""
    try:
        with db_helpers.connect() as conn:
            from yoke_core.domain.sessions_lifecycle_release import (
                release_item_claim_for_execution,
            )
            release_item_claim_for_execution(
                conn, session_id, str(item_id), reason,
            )
    except Exception:
        pass


def _run_preflight_gates(item_id: int, *, force: bool) -> Tuple[bool, str]:
    """Hard-block dep + AC presence + spec coverage. Returns (ok, narrative)."""
    if force:
        return True, ""
    from yoke_core.domain import check_hard_blocks
    from yoke_core.domain import check_ac_presence
    from yoke_core.domain import path_claim_spec_coverage_gate

    blockers = check_hard_blocks.evaluate_blockers(
        item_id, gate_filter="activation",
    )
    if blockers:
        return False, "Blocked by dependencies:\n  " + "\n  ".join(blockers)
    canonical, _unlabeled, title = check_ac_presence.evaluate_item(item_id)
    if title is None:
        return False, f"YOK-{item_id} not found in DB."
    if canonical <= 0:
        return False, (
            f"YOK-{item_id} has no acceptance criteria. Add "
            f"`## Acceptance Criteria` with `- [ ] AC-N: ...` checkboxes."
        )
    cov = path_claim_spec_coverage_gate.evaluate(item_id)
    if cov.is_blocked:
        return False, (
            f"BLOCKED: YOK-{item_id} File Budget lists "
            f"{len(cov.missing_paths)} path(s) not covered by any active "
            f"path_claim.\nMissing: " + ", ".join(cov.missing_paths)
        )
    return True, ""


def _resolve_env_repo_root(item: Dict[str, Any], worktree_path: str) -> str:
    """Resolve the local checkout used by worktree preflight."""
    project = item.get("project")
    if project:
        try:
            from yoke_core.domain.db_helpers import connect
            from yoke_core.domain.project_checkout_locations import checkout_for_project

            with connect() as conn:
                checkout = checkout_for_project(conn, str(project))
            if checkout is not None:
                return str(checkout)
        except Exception:
            pass
    if worktree_path:
        return os.path.dirname(os.path.dirname(worktree_path))
    return ""


def _run_environment_phase(
    item: Dict[str, Any], session_id: str,
    *, branch: str = "", repo_root: str = "",
) -> Tuple[str, Dict[str, Any]]:
    from yoke_core.engines.advance_implementation_environment import run as _r
    return _r(item=item, branch=branch, session_id=session_id,
              repo_root=repo_root)


def _flip_status(
    item_id: int, *, from_status: str, to_status: str, session_id: str,
    force: bool, qa_bypass: bool,
):
    from yoke_core.domain.yoke_function_dispatch import dispatch
    from yoke_contracts.api.function_call import (
        ActorContext, FunctionCallRequest, TargetRef,
    )
    return dispatch(FunctionCallRequest(
        function="lifecycle.transition.execute",
        actor=ActorContext(session_id=session_id),
        target=TargetRef(kind="item", item_id=int(item_id)),
        intent="advance_finalize",
        payload={
            "target_status": to_status, "source_status": from_status,
            "reason": "advance-implementation-entry",
            "force": force, "qa_bypass": qa_bypass,
        },
        options={"sync_github_body": True},
    ))


def run(
    item_id: Any, *, no_worktree: bool = False, force: bool = False,
    qa_bypass: bool = False, session_id: Optional[str] = None,
    actual_cwd: Optional[str] = None, out=sys.stdout,
) -> int:
    """Orchestrate the implementation-entry phases. Returns CLI exit code."""
    try:
        item_id_int = _parse_item_id(item_id)
    except ValueError:
        print(f"ERROR: invalid item id {item_id!r}", file=sys.stderr)
        return 2

    resolved_session = _resolve_session_id(session_id)
    item = _read_item(item_id_int)
    if item is None:
        print(f"ERROR: YOK-{item_id_int} not found.", file=sys.stderr)
        return 2

    pre_status = item.get("status") or ""
    is_reentry = pre_status in IMPLEMENTATION_PHASE_STATUSES
    # worktree_path / branch populated only on worktree-phase completion;
    # failure envelopes carry a structured ``error`` instead.
    summary: Dict[str, Any] = {
        "item_id": item_id_int, "title": item.get("title") or "",
        "pre_status": pre_status, "phases": [],
        "session_id": resolved_session, "reentry": is_reentry,
    }

    # Preflight gates ------------------------------------------
    t0 = time.monotonic()
    ok, narrative = _run_preflight_gates(item_id_int, force=force)
    dur = int((time.monotonic() - t0) * 1000)
    _record_phase(summary, item_id=item_id_int, phase=PHASE_PREFLIGHT,
                  outcome="completed" if ok else "blocked",
                  duration_ms=dur, session_id=resolved_session)
    if not ok:
        summary["error"] = {"phase": PHASE_PREFLIGHT, "kind": "gate_blocked",
                            "narrative": narrative}
        print(narrative, file=sys.stderr)
        print(json.dumps(summary), file=out)
        return 1

    # ``project`` lets worktree_preflight resolve the target project's
    # machine-local checkout for worktree and dirty-tree checks.
    from yoke_core.domain.worktree_preflight import run_preflight
    t0 = time.monotonic()
    wt = run_preflight(
        item_id=item_id_int, project=item.get("project"),
        session_id=resolved_session, actual_cwd=actual_cwd or "",
        no_worktree=no_worktree,
    )
    dur = int((time.monotonic() - t0) * 1000)
    if not wt.ok:
        outcome = f"blocked:{wt.block_kind}"
        _record_phase(summary, item_id=item_id_int, phase=PHASE_WORKTREE,
                      outcome=outcome, duration_ms=dur,
                      session_id=resolved_session,
                      context={"block_kind": wt.block_kind})
        print(wt.narrative, file=sys.stderr)
        if wt.block_kind == "worktree-create-failed":
            _release_claim(item_id_int, resolved_session,
                           RELEASE_WORKTREE_CREATE_FAILED)
        summary["error"] = {"phase": PHASE_WORKTREE,
                            "kind": wt.block_kind, "narrative": wt.narrative}
        print(json.dumps(summary), file=out)
        return 1
    _record_phase(summary, item_id=item_id_int, phase=PHASE_WORKTREE,
                  outcome="completed", duration_ms=dur,
                  session_id=resolved_session,
                  context={"branch": wt.branch,
                           "worktree_path": wt.worktree_path,
                           "actions_taken": list(wt.actions_taken)})
    summary["worktree_path"] = wt.worktree_path
    summary["branch"] = wt.branch

    # Environment ----------------------------------------------
    t0 = time.monotonic()
    env_outcome, env_ctx = _run_environment_phase(
        item, resolved_session, branch=wt.branch,
        repo_root=_resolve_env_repo_root(item, wt.worktree_path),
    )
    dur = int((time.monotonic() - t0) * 1000)
    _record_phase(summary, item_id=item_id_int, phase=PHASE_ENVIRONMENT,
                  outcome=env_outcome, duration_ms=dur,
                  session_id=resolved_session, context=env_ctx)

    # Finalize (status flip) -----------------------------------
    t0 = time.monotonic()
    if is_reentry:
        _record_phase(summary, item_id=item_id_int, phase=PHASE_FINALIZE,
                      outcome="skipped:already-past-refined-idea",
                      duration_ms=int((time.monotonic() - t0) * 1000),
                      session_id=resolved_session,
                      context={"current_status": pre_status})
        summary["post_status"] = pre_status
        print(json.dumps(summary), file=out)
        return 0

    target_status = "implementing"
    response = _flip_status(
        item_id_int, from_status=pre_status, to_status=target_status,
        session_id=resolved_session, force=force, qa_bypass=qa_bypass,
    )
    dur = int((time.monotonic() - t0) * 1000)
    if not response.success:
        code = response.error.code if response.error else "unknown"
        msg = response.error.message if response.error else "transition failed"
        _record_phase(summary, item_id=item_id_int, phase=PHASE_FINALIZE,
                      outcome=f"blocked:{code}", duration_ms=dur,
                      session_id=resolved_session,
                      context={"error_code": code, "message": msg})
        print(f"ERROR: finalize failed ({code}): {msg}", file=sys.stderr)
        # Keep the claim — implementing-eligible state remains valid
        # for re-entry. The orchestrator is idempotent on re-run.
        summary["error"] = {"phase": PHASE_FINALIZE, "kind": code,
                            "narrative": msg}
        print(json.dumps(summary), file=out)
        return 1

    _record_phase(summary, item_id=item_id_int, phase=PHASE_FINALIZE,
                  outcome="completed", duration_ms=dur,
                  session_id=resolved_session,
                  context={"from_status": pre_status,
                           "to_status": target_status})
    summary["post_status"] = target_status
    print(json.dumps(summary), file=out)
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="advance-implementation-entry")
    parser.add_argument("--item", required=True,
                        help="Item ID (YOK-N, N, or padded form)")
    parser.add_argument("--no-worktree", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--qa-bypass", action="store_true")
    parser.add_argument("--session-id", default=None)
    args = parser.parse_args(argv)
    try:
        return run(args.item, no_worktree=args.no_worktree, force=args.force,
                   qa_bypass=args.qa_bypass, session_id=args.session_id)
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - surface and exit non-zero
        print(f"ERROR: orchestrator crashed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
