"""Board, frontier, and schedule command handlers for the service_client CLI surface.

This module contains the charge-frontier and charge-schedule commands plus
their associated serialisation helpers, extracted from the monolithic
service_client.py.
"""

from __future__ import annotations

import json
import sys

from yoke_core.api.service_client_shared import (
    _get_db_readonly,
    AdapterCategory,
    FrontierItem,
    FrontierResult,
    compute_domain_frontier,
    compute_schedule,
)
from yoke_core.domain.session_project_scope import (
    parse_project_cli_arg,
    resolve_session_project_scope,
)


def _resolve_default_wip_cap(project_scope: list[int]) -> int:
    """DB-backed WIP cap when no ``--wip-cap`` flag was passed.

    A single-project scope reads the project's ``project-policy`` capability;
    multi-project scopes use the source default.
    """
    from yoke_core.domain.project_settings import get_project_int_for_id

    project_id = project_scope[0] if len(project_scope) == 1 else None
    return get_project_int_for_id(project_id, "wip_cap")


# ---------------------------------------------------------------------------
# charge-frontier
# ---------------------------------------------------------------------------


def _frontier_item_to_dict(fi: FrontierItem) -> dict:
    """Convert a FrontierItem dataclass to a JSON-serializable dict."""
    return {
        "item_id": fi.item_id,
        "title": fi.title,
        "status": fi.status,
        "priority": fi.priority,
        "project": fi.project,
        "item_type": fi.item_type,
        "adapter": fi.adapter.value if isinstance(fi.adapter, AdapterCategory) else fi.adapter,
        "blocked_by": fi.blocked_by,
        "blocked_reasons": fi.blocked_reasons,
        "unblocks_count": fi.unblocks_count,
        "downstream_depth": fi.downstream_depth,
        "created_at": fi.created_at,
    }


def _frontier_result_to_dict(fr: FrontierResult) -> dict:
    """Convert a FrontierResult dataclass to a JSON-serializable dict."""
    return {
        "runnable": [_frontier_item_to_dict(i) for i in fr.runnable],
        "blocked": [_frontier_item_to_dict(i) for i in fr.blocked],
        "frozen": [_frontier_item_to_dict(i) for i in fr.frozen],
        "wip_cap": fr.wip_cap,
        "wip_active": fr.wip_active,
        "conduct_eligible": [_frontier_item_to_dict(i) for i in fr.conduct_eligible],
    }


def cmd_charge_frontier(args: list[str]) -> int:
    """Compute and print the runnable frontier as JSON.

    Usage: charge-frontier [--project P] [--wip-cap N]

    Calls compute_frontier() directly (direct DB access, not via HTTP).
    Prints the FrontierResult as JSON to stdout. Without ``--wip-cap``
    the cap resolves from project-policy for single-project scopes, else 5.

    Exit 0 on success, 1 on error, 2 on usage error.
    """
    project = None
    wip_cap = None

    i = 0
    while i < len(args):
        if args[i] == "--project" and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        elif args[i] == "--wip-cap" and i + 1 < len(args):
            try:
                wip_cap = int(args[i + 1])
            except ValueError:
                print(f"Error: --wip-cap must be an integer, got '{args[i + 1]}'",
                      file=sys.stderr)
                return 1
            if wip_cap < 1 or wip_cap > 100:
                print(f"Error: --wip-cap must be between 1 and 100, got {wip_cap}",
                      file=sys.stderr)
                return 1
            i += 2
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            return 2

    conn = _get_db_readonly()
    try:
        try:
            project_scope = resolve_session_project_scope(
                conn, override=parse_project_cli_arg(project),
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        if wip_cap is None:
            wip_cap = _resolve_default_wip_cap(project_scope)
        result = compute_domain_frontier(
            conn, project_scope=project_scope, wip_cap=wip_cap,
        )
        print(json.dumps(_frontier_result_to_dict(result)))
        return 0
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# charge-schedule
# ---------------------------------------------------------------------------


def _scheduled_step_to_dict(step) -> dict:
    """Convert a ScheduledStep to a JSON-serializable dict."""
    return {
        "item_id": step.item_id,
        "item_type": step.item_type,
        "status": step.status,
        "title": step.title,
        "priority": step.priority,
        "next_step": step.next_step.value if hasattr(step.next_step, "value") else str(step.next_step),
        "rank": step.rank,
        "claim_state": step.claim_state.value if hasattr(step.claim_state, "value") else str(step.claim_state),
        "gate_evaluations": [
            {
                "blocking_item": ge.blocking_item,
                "relation": ge.relation,
                "gate_point": ge.gate_point,
                "satisfaction": ge.satisfaction,
                "satisfied": ge.satisfied,
                "reason": ge.reason,
                "rationale": getattr(ge, "rationale", ""),
            }
            for ge in step.gate_evaluations
        ],
        "explanation": step.explanation,
        "adapter": step.adapter,
        "blocked_by": step.blocked_by,
        "blocked_reasons": step.blocked_reasons,
        "unblocks_count": step.unblocks_count,
        "downstream_depth": step.downstream_depth,
        "created_at": step.created_at,
    }


def _scheduler_result_to_dict(sr) -> dict:
    """Convert a SchedulerResult to a JSON-serializable dict."""
    return {
        "project_scope": list(sr.project_scope),
        "sml_state": {
            "coherent": sr.sml_state.coherent,
        },
        "selected_step": _scheduled_step_to_dict(sr.selected_step) if sr.selected_step else None,
        "ranked_steps": [_scheduled_step_to_dict(s) for s in sr.ranked_steps],
        "blocked_steps": [_scheduled_step_to_dict(s) for s in sr.blocked_steps],
        "exceptional_steps": [_scheduled_step_to_dict(s) for s in sr.exceptional_steps],
        "wip_cap": sr.wip_cap,
        "wip_active": sr.wip_active,
        "conduct_eligible": [_scheduled_step_to_dict(s) for s in sr.conduct_eligible],
        "frozen_steps": [_scheduled_step_to_dict(s) for s in sr.frozen_steps],
    }


def cmd_charge_schedule(args: list[str]) -> int:
    """Compute and print the shared scheduler result as JSON.

    Usage: charge-schedule [--project P] [--wip-cap N]

    Calls compute_schedule() directly (direct DB access, not via HTTP).
    Returns the full scheduler result with type-aware next-step routing,
    SML state, and deterministic ranking. Without ``--wip-cap`` the cap
    resolves from project-policy for single-project scopes, else 5.
    """
    project = None
    wip_cap = None

    i = 0
    while i < len(args):
        if args[i] == "--project" and i + 1 < len(args):
            project = args[i + 1]
            i += 2
        elif args[i] == "--wip-cap" and i + 1 < len(args):
            try:
                wip_cap = int(args[i + 1])
            except ValueError:
                print(f"Error: --wip-cap must be an integer, got '{args[i + 1]}'",
                      file=sys.stderr)
                return 1
            if wip_cap < 1 or wip_cap > 100:
                print(f"Error: --wip-cap must be between 1 and 100, got {wip_cap}",
                      file=sys.stderr)
                return 1
            i += 2
        else:
            print(f"Unknown argument: {args[i]}", file=sys.stderr)
            return 2

    conn = _get_db_readonly()
    try:
        try:
            project_scope = resolve_session_project_scope(
                conn, override=parse_project_cli_arg(project),
            )
        except ValueError as exc:
            print(f"Error: {exc}", file=sys.stderr)
            return 1
        if wip_cap is None:
            wip_cap = _resolve_default_wip_cap(project_scope)
        result = compute_schedule(
            conn, project_scope=project_scope, wip_cap=wip_cap,
        )
        print(json.dumps(_scheduler_result_to_dict(result)))
        return 0
    finally:
        conn.close()
