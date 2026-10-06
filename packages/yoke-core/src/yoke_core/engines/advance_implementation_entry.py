"""Implementation entry: gates, worktree, environment, and status finalize.

CLI: ``python3 -m yoke_core.engines.advance_implementation_entry --item
YOK-N [--no-worktree] [--force] [--qa-bypass] [--session-id X]``.
"""

from __future__ import annotations

from yoke_core.domain.public_item_target import public_item_target

import argparse
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

from yoke_contracts.api.function_call import ActorContext
from yoke_core.api.service_client_structured_api_adapter import call_dispatcher
from yoke_core.domain.events import TRANSPORT_NO_LOCAL_DB_REASON, emit_event


PHASE_PREFLIGHT = "preflight"
PHASE_WORKTREE = "worktree"
PHASE_ENVIRONMENT = "environment"
PHASE_FINALIZE = "finalize"

RELEASE_WORKTREE_CREATE_FAILED = "worktree-create-failed"

IMPLEMENTATION_PHASE_STATUSES = frozenset(
    {
        "implementing",
        "reviewing-implementation",
        "reviewed-implementation",
        "polishing-implementation",
        "implemented",
        "release",
        "done",
    }
)


def _parse_item_argument(raw: Any) -> int:
    """Resolve an item ref to the internal ``items.id``.

    ``PREFIX-N`` resolves through the project's ``public_item_prefix`` +
    ``items.project_sequence``; a bare number is a project-local sequence.
    """
    from yoke_core.domain.yok_n_parser import parse_item_argument

    return parse_item_argument(raw)


def _read_item(item_id: int) -> Optional[Dict[str, Any]]:
    """Read the item's routing fields through the transport-aware relay.

    Routes ``items.detail.get`` through ``call_dispatcher`` so the read
    works over an https control plane as well as an in-process local
    Postgres connection. Returns ``None`` when the item is not found (or
    the read is refused), matching the previous local-query contract.
    """
    response = call_dispatcher(
        function_id="items.detail.get",
        target=public_item_target(item_id),
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
        "public_ref": item.get("public_ref"),
        "workflow_id": workflow.get("id"),
        "workflow_version_id": workflow.get("version_id"),
        "status": item.get("status"),
        "title": item.get("title"),
        "project": project.get("slug"),
    }


def _record_phase(
    summary: Dict[str, Any],
    *,
    item_id: int,
    phase: str,
    outcome: str,
    duration_ms: int,
    session_id: str,
    context: Optional[Dict[str, Any]] = None,
) -> None:
    """Emit ``AdvancePhaseCompleted`` and append to summary in one pass."""
    payload: Dict[str, Any] = {
        "phase": phase,
        "outcome": outcome,
        "duration_ms": int(duration_ms),
    }
    if context:
        payload.update(context)
    result = emit_event(
        "AdvancePhaseCompleted",
        event_kind="workflow",
        event_type="advance_phase",
        session_id=session_id,
        item_id=str(item_id),
        context=payload,
    )
    # Over an https control plane there is no local DB to write client-side
    # telemetry to; that is a best-effort drop, not a failure to surface.
    if (
        result is not None
        and not result.ok
        and getattr(result, "reason", "") != TRANSPORT_NO_LOCAL_DB_REASON
    ):
        raise RuntimeError(f"AdvancePhaseCompleted emission failed: {result.reason}")
    summary["phases"].append(
        {"phase": phase, "outcome": outcome, "duration_ms": int(duration_ms)}
    )


def _release_claim(item_id: int, session_id: str, reason: str) -> None:
    """Best-effort release through the transport-aware relay. Never raises."""
    try:
        call_dispatcher(
            function_id="claims.work.release",
            target=public_item_target(item_id),
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
    item: Dict[str, Any],
    session_id: str,
    *,
    branch: str = "",
    repo_root: str = "",
) -> Tuple[str, Dict[str, Any]]:
    from yoke_core.engines.advance_implementation_environment import run as _r

    return _r(item=item, branch=branch, session_id=session_id, repo_root=repo_root)


def _flip_status(
    item_id: int,
    *,
    from_status: str,
    to_status: str,
    session_id: str,
    force: bool,
    qa_bypass: bool,
):
    # Route through the transport-aware facade so the transition executes
    # over an https control plane as well as an in-process local Postgres
    # connection. On a local connection this dispatches the same
    # ``lifecycle.transition.execute`` call in-process.
    return call_dispatcher(
        function_id="lifecycle.transition.execute",
        actor=ActorContext(session_id=session_id),
        target=public_item_target(item_id),
        intent="advance_finalize",
        payload={
            "target_status": to_status,
            "source_status": from_status,
            "reason": "advance-implementation-entry",
            "force": force,
            "qa_bypass": qa_bypass,
        },
        options={"sync_github_body": True},
    )


def run(item_id: Any, **kwargs: Any) -> int:
    """Run host entry orchestration using this module's injected helper seams."""
    from yoke_core.engines.advance_implementation_run import run as run_entry

    return run_entry(item_id, **kwargs)


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(prog="advance-implementation-entry")
    parser.add_argument(
        "--item", required=True, help="Item ID (YOK-N, N, or padded form)"
    )
    parser.add_argument("--no-worktree", action="store_true")
    parser.add_argument(
        "--force",
        action="store_true",
        help=(
            "Override dependency and effective File Budget preflight; "
            "acceptance criteria are checked at Refine closure."
        ),
    )
    parser.add_argument("--qa-bypass", action="store_true")
    parser.add_argument("--session-id", default=None)
    args = parser.parse_args(argv)
    try:
        return run(
            args.item,
            no_worktree=args.no_worktree,
            force=args.force,
            qa_bypass=args.qa_bypass,
            session_id=args.session_id,
        )
    except SystemExit:
        raise
    except Exception as exc:  # noqa: BLE001 - surface and exit non-zero
        print(f"ERROR: orchestrator crashed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
