"""Host implementation entry orchestration through public item identity."""

from __future__ import annotations

import json
import sys
import time
from typing import Any, Dict, Optional

from yoke_core.engines import advance_implementation_entry as entry


def run(
    item_id: Any,
    *,
    no_worktree: bool = False,
    force: bool = False,
    qa_bypass: bool = False,
    session_id: Optional[str] = None,
    actual_cwd: Optional[str] = None,
    out=sys.stdout,
) -> int:
    """Orchestrate the implementation-entry phases. Returns CLI exit code."""
    try:
        public_ref = entry.public_item_target(item_id).public_ref
    except ValueError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2

    resolved_session, identity_kind, identity_narrative = entry._probe_session_identity(
        session_id
    )
    if identity_kind:
        error = {
            "phase": entry.PHASE_PREFLIGHT,
            "kind": identity_kind,
            "narrative": identity_narrative,
        }
        print(identity_narrative, file=sys.stderr)
        print(
            json.dumps(
                {
                    "public_ref": public_ref,
                    "phases": [],
                    "session_id": "",
                    "error": error,
                }
            ),
            file=out,
        )
        return 1
    item = entry._read_item(public_ref)
    if item is None:
        print(f"ERROR: no item for {item_id!r}.", file=sys.stderr)
        return 2

    pre_status = item.get("status") or ""
    is_reentry = pre_status in entry.IMPLEMENTATION_PHASE_STATUSES
    # worktree_path / branch populated only on worktree-phase completion;
    # failure envelopes carry a structured ``error`` instead.
    summary: Dict[str, Any] = {
        "public_ref": public_ref,
        "title": item.get("title") or "",
        "pre_status": pre_status,
        "phases": [],
        "session_id": resolved_session,
        "reentry": is_reentry,
    }

    # Preflight gates ------------------------------------------
    t0 = time.monotonic()
    ok, narrative = entry._run_preflight_gates(public_ref, force=force)
    dur = int((time.monotonic() - t0) * 1000)
    entry._record_phase(
        summary,
        item_id=public_ref,
        phase=entry.PHASE_PREFLIGHT,
        outcome="completed" if ok else "blocked",
        duration_ms=dur,
        session_id=resolved_session,
    )
    if not ok:
        summary["error"] = {
            "phase": entry.PHASE_PREFLIGHT,
            "kind": "gate_blocked",
            "narrative": narrative,
        }
        print(narrative, file=sys.stderr)
        print(json.dumps(summary), file=out)
        return 1

    # ``project`` lets worktree_preflight resolve the target project's
    # machine-local checkout for worktree and dirty-tree checks.
    from yoke_core.domain.worktree_preflight import run_preflight

    t0 = time.monotonic()
    wt = run_preflight(
        item_id=public_ref,
        project=item.get("project"),
        session_id=resolved_session,
        actual_cwd=actual_cwd or "",
        no_worktree=no_worktree,
    )
    dur = int((time.monotonic() - t0) * 1000)
    if not wt.ok:
        outcome = f"blocked:{wt.block_kind}"
        entry._record_phase(
            summary,
            item_id=public_ref,
            phase=entry.PHASE_WORKTREE,
            outcome=outcome,
            duration_ms=dur,
            session_id=resolved_session,
            context={"block_kind": wt.block_kind},
        )
        print(wt.narrative, file=sys.stderr)
        if wt.block_kind == "worktree-create-failed":
            entry._release_claim(
                public_ref, resolved_session, entry.RELEASE_WORKTREE_CREATE_FAILED
            )
        summary["error"] = {
            "phase": entry.PHASE_WORKTREE,
            "kind": wt.block_kind,
            "narrative": wt.narrative,
        }
        print(json.dumps(summary), file=out)
        return 1
    entry._record_phase(
        summary,
        item_id=public_ref,
        phase=entry.PHASE_WORKTREE,
        outcome="completed",
        duration_ms=dur,
        session_id=resolved_session,
        context={
            "branch": wt.branch,
            "worktree_path": wt.worktree_path,
            "actions_taken": list(wt.actions_taken),
        },
    )
    summary["worktree_path"] = wt.worktree_path
    summary["branch"] = wt.branch
    # Upstream freshness and static-cwd advisories reach the operator only
    # if the orchestrator carries the preflight's notes into its own output.
    summary["notes"] = list(wt.notes)
    for note in wt.notes:
        print(note, file=sys.stderr)

    # Environment ----------------------------------------------
    t0 = time.monotonic()
    env_outcome, env_ctx = entry._run_environment_phase(
        item,
        resolved_session,
        branch=wt.branch,
        repo_root=entry._resolve_env_repo_root(item, wt.worktree_path),
    )
    dur = int((time.monotonic() - t0) * 1000)
    entry._record_phase(
        summary,
        item_id=public_ref,
        phase=entry.PHASE_ENVIRONMENT,
        outcome=env_outcome,
        duration_ms=dur,
        session_id=resolved_session,
        context=env_ctx,
    )

    # Finalize (status flip) -----------------------------------
    t0 = time.monotonic()
    if is_reentry:
        entry._record_phase(
            summary,
            item_id=public_ref,
            phase=entry.PHASE_FINALIZE,
            outcome="skipped:already-past-refined-idea",
            duration_ms=int((time.monotonic() - t0) * 1000),
            session_id=resolved_session,
            context={"current_status": pre_status},
        )
        summary["post_status"] = pre_status
        print(json.dumps(summary), file=out)
        return 0

    target_status = "implementing"
    response = entry._flip_status(
        public_ref,
        from_status=pre_status,
        to_status=target_status,
        session_id=resolved_session,
        force=force,
        qa_bypass=qa_bypass,
    )
    dur = int((time.monotonic() - t0) * 1000)
    if not response.success:
        code = response.error.code if response.error else "unknown"
        msg = response.error.message if response.error else "transition failed"
        entry._record_phase(
            summary,
            item_id=public_ref,
            phase=entry.PHASE_FINALIZE,
            outcome=f"blocked:{code}",
            duration_ms=dur,
            session_id=resolved_session,
            context={"error_code": code, "message": msg},
        )
        print(f"ERROR: finalize failed ({code}): {msg}", file=sys.stderr)
        # Keep the claim — implementing-eligible state remains valid
        # for re-entry. The orchestrator is idempotent on re-run.
        summary["error"] = {
            "phase": entry.PHASE_FINALIZE,
            "kind": code,
            "narrative": msg,
        }
        print(json.dumps(summary), file=out)
        return 1

    entry._record_phase(
        summary,
        item_id=public_ref,
        phase=entry.PHASE_FINALIZE,
        outcome="completed",
        duration_ms=dur,
        session_id=resolved_session,
        context={"from_status": pre_status, "to_status": target_status},
    )
    summary["post_status"] = target_status
    print(json.dumps(summary), file=out)
    return 0
