"""Dependency-planning CLI commands.

Owns ``evaluate-gate`` (single-item gate evaluation at a named gate
point) and ``plan-candidates`` (topological set planning for a batch of
candidate items at the same gate point). Both commands wrap the shared
dependency-planning kernel and only handle CLI argument parsing,
``YOK-N`` normalization, and JSON serialisation here.
"""

from __future__ import annotations

import json
import sys

from yoke_core.api.service_client_shared import (
    _get_db_readonly,
    evaluate_item_gate,
    plan_candidate_set,
)
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.yok_n_parser import parse_item_argument


def _blocker_detail_to_dict(b) -> dict:
    """Convert a BlockerDetail to a JSON-serializable dict."""
    return b.to_dict()


def cmd_evaluate_gate(args: list[str]) -> int:
    """Evaluate dependencies for one item at a gate point.

    Usage: evaluate-gate <item-id> <gate-point>

    Calls the shared dependency-planning kernel directly.
    Prints JSON with is_blocked, unsatisfied_blockers, etc.

    Exit 0 on success (even when blocked -- the JSON indicates that),
    1 on domain error, 2 on usage error.
    """
    if len(args) < 2:
        print("Usage: evaluate-gate <item-id> <gate-point>", file=sys.stderr)
        return 2

    item_id = args[0]
    gate_point = args[1]

    conn = _get_db_readonly()
    try:
        # Resolve the ref (PREFIX-N via its own prefix; bare N via the mapped
        # checkout project) and re-render the canonical text ref stored by the
        # dependency rows.
        resolved = parse_item_argument(item_id, conn=conn)
        item_id = render_item_ref(conn, resolved)
        result = evaluate_item_gate(conn, item_id, gate_point)
        out = {
            "item_id": result.item_id,
            "gate_point": result.gate_point,
            "is_blocked": result.is_blocked,
            "unsatisfied_blockers": [
                _blocker_detail_to_dict(b)
                for b in result.unsatisfied_blockers
            ],
        }
        print(json.dumps(out))
        return 0
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()


def cmd_plan_candidates(args: list[str]) -> int:
    """Plan a candidate set at a specific gate point.

    Usage: plan-candidates <gate-point> <item1> [item2 ...]

    Calls the shared dependency-planning kernel directly.
    Prints JSON with eligible (in topological order), blocked, has_cycle.

    Exit 0 on success, 1 on domain error, 2 on usage error.
    """
    if len(args) < 2:
        print("Usage: plan-candidates <gate-point> <item1> [item2 ...]",
              file=sys.stderr)
        return 2

    gate_point = args[0]

    conn = _get_db_readonly()
    try:
        candidate_ids = []
        for raw in args[1:]:
            resolved = parse_item_argument(raw, conn=conn)
            candidate_ids.append(render_item_ref(conn, resolved))
        result = plan_candidate_set(conn, candidate_ids, gate_point)
        out = {
            "gate_point": result.gate_point,
            "eligible": result.eligible,
            "blocked": [
                {
                    "item_id": c.item_id,
                    "blockers": [_blocker_detail_to_dict(b) for b in c.blockers],
                }
                for c in result.blocked
            ],
            "has_cycle": result.has_cycle,
            "cycle_items": result.cycle_items,
        }
        print(json.dumps(out))
        return 0
    except ValueError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        conn.close()
