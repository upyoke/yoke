"""Implementation entry: gates, worktree, environment, and status finalize.

CLI: ``python3 -m yoke_core.engines.advance_implementation_entry --item
YOK-N [--no-worktree] [--force] [--qa-bypass] [--session-id X]``.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional, Tuple

from yoke_contracts.api.function_call import ActorContext, TargetRef
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.events import TRANSPORT_NO_LOCAL_DB_REASON, emit_event
from yoke_core.engines.advance_implementation_preflight_gates import (
    _probe_session_identity,
    _run_preflight_gates,
)


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
    """Resolve an item ref to the internal ``items.id``.

    ``PREFIX-N`` resolves through the project's ``public_item_prefix`` +
    ``items.project_sequence``; a bare number stays an internal id.
    """
    from yoke_core.domain.yok_n_parser import parse_item_id

    return parse_item_id(raw, allow_bare_internal=True)


def _read_item(item_id: int) -> Optional[Dict[str, Any]]:
    """Read the item's routing fields through the transport-aware relay.

    Routes ``items.detail.get`` through ``call_dispatcher`` so the read
    works over an https control plane as well as an in-process local
    Postgres connection. Returns ``None`` when the item is not found (or
    the read is refused), matching the previous local-query contract.
    """
    response = call_dispatcher(
        function_id="items.detail.get",
        target=TargetRef(kind="item", item_id=int(item_id)),
        payload={},
    )
    if not response.success:
        return None
    item = (response.result or {}).get("item") or {}
    if not item:
        return None
    workflow = item.get("workflow") or {}
    project = item.get("project") or {}
    return {
        "id": item.get("id"),
        "workflow_id": workflow.get("id"),
        "workflow_version_id": workflow.get("version_id"),
        "status": item.get("status"),
        "title": item.get("title"),
        "project": project.get("slug"),
    }


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
    # Over an https control plane there is no local DB to write client-side
    # telemetry to; that is a best-effort drop, not a failure to surface.
    if (
        result is not None
        and not result.ok
        and getattr(result, "reason", "") != TRANSPORT_NO_LOCAL_DB_REASON
    ):
        raise RuntimeError(
            f"AdvancePhaseCompleted emission failed: {result.reason}"
        )
    summary["phases"].append({"phase": phase, "outcome": outcome,
                              "duration_ms": int(duration_ms)})


def _release_claim(item_id: int, session_id: str, reason: str) -> None:
    """Best-effort release through the transport-aware relay. Never raises."""
    try:
        call_dispatcher(
            function_id="claims.work.release",
            target=TargetRef(kind="item", item_id=int(item_id)),
            actor=ActorContext(session_id=session_id),
            payload={"reason": reason},
        )
    except Exception:
        pass


def _resolve_env_repo_root(item: Dict[str, Any], worktree_path: str) -> str:
    """Resolve the local checkout used by worktree preflight.

    The project-slug-to-checkout resolution routes through the
    transport-aware ``checkout_for_project_slug`` (relays ``projects.get``,
    then reads the machine-local checkout mapping), so it works over an
    https control plane as well as an in-process local Postgres connection.
    Falls back to the worktree-path-derived repo root when no machine-local
    checkout is mapped.
    """
    project = item.get("project")
    if project:
        try:
            from yoke_core.domain.project_checkout_locations import (
                checkout_for_project_slug,
            )

            checkout = checkout_for_project_slug(str(project))
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
    # Route through the transport-aware facade so the transition executes
    # over an https control plane as well as an in-process local Postgres
    # connection. On a local connection this dispatches the same
    # ``lifecycle.transition.execute`` call in-process.
    return call_dispatcher(
        function_id="lifecycle.transition.execute",
        actor=ActorContext(session_id=session_id),
        target=TargetRef(kind="item", item_id=int(item_id)),
        intent="advance_finalize",
        payload={
            "target_status": to_status, "source_status": from_status,
            "reason": "advance-implementation-entry",
            "force": force, "qa_bypass": qa_bypass,
        },
        options={"sync_github_body": True},
    )


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

    resolved_session, identity_kind, identity_narrative = (
        _probe_session_identity(session_id)
    )
    if identity_kind:
        error = {"phase": PHASE_PREFLIGHT, "kind": identity_kind,
                 "narrative": identity_narrative}
        print(identity_narrative, file=sys.stderr)
        print(json.dumps({"item_id": item_id_int, "phases": [],
                          "session_id": "", "error": error}), file=out)
        return 1
    item = _read_item(item_id_int)
    if item is None:
        print(f"ERROR: item {item_id!r} not found.", file=sys.stderr)
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
