"""Frontier computation orchestration and telemetry."""

from __future__ import annotations

import logging
import time
from typing import Any, Dict, List, Optional, Tuple

from . import db_backend
from .dependency_planning import evaluate_batch_gates
from .frontier_classify import classify_next_action
from .frontier_depth import _compute_downstream_depths
from .frontier_rank import rank_frontier
from .frontier_recent_owner import routed_ownership_exclusions
from .frontier_types import AdapterCategory, FrontierItem, FrontierResult
from .idea_body_completeness import (
    INCOMPLETE_REASON as _IDEA_INCOMPLETE_REASON,
    is_idea_body_incomplete,
)
from .project_identity import resolve_project_slug
from .project_scope import normalize_project_scope
from .queries import is_blocked, is_frozen, sql_frozen_filter
from .runtime_settings import get_seconds


_FRONTIER_ITEMS_SQL_PREFIX = """
SELECT
    i.id,
    i.title,
    i.status,
    i.priority,
    i.project_id AS project,
    i.type,
    i.frozen,
    i.blocked,
    i.blocked_reason,
    i.created_at,
    i.spec
FROM items i
WHERE i.status IN (
    'idea', 'planned', 'release',
    'blocked',
    'refining-idea', 'refined-idea',
    'implementing', 'reviewing-implementation', 'reviewed-implementation',
    'polishing-implementation', 'implemented',
    'planning', 'plan-drafted', 'refining-plan'
)
"""

_FRONTIER_ITEMS_SQL_SUFFIX = " ORDER BY i.id"

_UNBLOCKS_COUNT_SQL = """
SELECT
    d.blocking_item,
    COUNT(DISTINCT d.dependent_item) AS unblocks
FROM item_dependencies d
WHERE d.gate_point = 'activation'
GROUP BY d.blocking_item
"""

_WIP_COUNT_SQL_PREFIX = """
SELECT COUNT(*) FROM items
WHERE status IN ('implementing', 'reviewing-implementation')
"""


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _project_scope_clause(conn: Any, project_scope: List[int]) -> str:
    """Build an ``AND i.project_id IN (...)`` clause for the scope ids."""
    if not project_scope:
        return " AND 1=0"
    placeholders = ", ".join(_p(conn) for _ in project_scope)
    return f" AND i.project_id IN ({placeholders})"


def _wip_project_scope_clause(conn: Any, project_scope: List[int]) -> str:
    """Same as ``_project_scope_clause`` for the unaliased WIP query."""
    if not project_scope:
        return " AND 1=0"
    placeholders = ", ".join(_p(conn) for _ in project_scope)
    return f" AND project_id IN ({placeholders})"


def compute_frontier(
    conn: Any,
    project_scope: List[Any],
    wip_cap: int = 5,
    session_id: Optional[str] = None,
    emit_events: bool = True,
) -> FrontierResult:
    """Compute the runnable frontier for the numeric project-id scope.

    ``emit_events=False`` suppresses the ``FrontierComputed`` and
    ``DependencyGateEvaluated`` telemetry writes so pure reads (e.g. a
    browser poll) leave no event rows behind; the default preserves
    emission for every existing caller.
    """
    _t0 = time.monotonic()
    project_scope = normalize_project_scope(conn, project_scope)
    cursor = conn.cursor()

    project_clause = _project_scope_clause(conn, project_scope)
    items_sql = _FRONTIER_ITEMS_SQL_PREFIX + project_clause + _FRONTIER_ITEMS_SQL_SUFFIX
    cursor.execute(items_sql, tuple(project_scope))
    rows = cursor.fetchall()
    col_names = [desc[0] for desc in cursor.description]

    activation_blocks = evaluate_batch_gates(
        conn,
        gate_point="activation",
        session_id=session_id,
        project=_canonical_project_label(conn, project_scope),
        emit_events=emit_events,
    )

    hard_blocks: Dict[str, List[Tuple[str, str]]] = {}
    blocker_details_map: Dict[str, List[Dict[str, Any]]] = {}
    for dep_item, details in activation_blocks.items():
        hard_blocks[dep_item] = [
            (d.blocking_item, d.blocking_status or "unknown") for d in details
        ]
        blocker_details_map[dep_item] = [d.to_dict() for d in details]

    cursor.execute(_UNBLOCKS_COUNT_SQL)
    unblocks_map: Dict[str, int] = {}
    for blk_item, count in cursor.fetchall():
        unblocks_map[blk_item] = count

    depth_map = _compute_downstream_depths(conn)

    frozen_filter = sql_frozen_filter(False)
    wip_project_clause = _wip_project_scope_clause(conn, project_scope)
    wip_sql = _WIP_COUNT_SQL_PREFIX + wip_project_clause + f" AND ({frozen_filter})"
    cursor.execute(wip_sql, tuple(project_scope))
    wip_active = cursor.fetchone()[0]

    recent_owner_window_s = get_seconds(
        "session_reactivation_reacquire_window_s", 300,
    )
    defended_items = routed_ownership_exclusions(
        conn,
        window_s=recent_owner_window_s,
        requesting_session_id=session_id,
    )

    runnable: List[FrontierItem] = []
    blocked: List[FrontierItem] = []
    frozen_items: List[FrontierItem] = []
    excluded_routed_ownership: List[Dict[str, Any]] = []
    project_labels: Dict[int, str] = {}

    def _project_label(project_id: Any) -> str:
        pid = int(project_id)
        if pid not in project_labels:
            project_labels[pid] = resolve_project_slug(conn, pid)
        return project_labels[pid]

    for row in rows:
        item = dict(zip(col_names, row))
        item_id_str = f"YOK-{item['id']}"
        status = item["status"]

        adapter = classify_next_action(status, item_type=item["type"])

        fi = FrontierItem(
            item_id=item_id_str,
            title=item["title"],
            status=status,
            priority=item["priority"],
            project=_project_label(item["project"]),
            item_type=item["type"],
            adapter=adapter,
            unblocks_count=unblocks_map.get(item_id_str, 0),
            downstream_depth=depth_map.get(item_id_str, 0),
            created_at=item["created_at"],
        )

        if is_frozen(item["frozen"]):
            frozen_items.append(fi)
            continue

        blockers = hard_blocks.get(item_id_str, [])
        flag_blocked = is_blocked(item.get("blocked"))
        if flag_blocked:
            # Render operator-set blocks verbatim so dispatch names the real reason.
            reason = item.get("blocked_reason") or ""
            if reason:
                fi.blocked_reasons.append(f"Blocked by operator: {reason}")
            else:
                fi.blocked_reasons.append("Blocked by operator.")
        elif status == "blocked":
            # Legacy drift: post-cutover this status should not appear.
            fi.blocked_reasons.append(
                "Item is in legacy blocked status; resolve the blocking issue before dispatch."
            )

        if blockers:
            fi.blocked_by = [b[0] for b in blockers]
            fi.blocked_reasons.extend(
                f"Blocked by {b[0]} (status: {b[1]})" for b in blockers
            )
            fi.blocker_details = blocker_details_map.get(item_id_str, [])

        idea_incomplete = status == "idea" and is_idea_body_incomplete(item)
        if idea_incomplete:
            fi.blocked_reasons.append(
                f"{_IDEA_INCOMPLETE_REASON}: idea body is title-only "
                "(no spec content yet). Either /yoke idea is still in flight "
                "or a prior draft session crashed before persisting the spec. "
                "Run /yoke doctor to inspect."
            )

        if flag_blocked or status == "blocked" or blockers or idea_incomplete:
            fi.adapter = AdapterCategory.WAIT
            blocked.append(fi)
        elif item_id_str in defended_items:
            fi.adapter = AdapterCategory.WAIT
            detail = defended_items[item_id_str]
            fi.blocked_reasons.append(_format_routed_ownership_reason(detail))
            excluded_routed_ownership.append(detail)
            blocked.append(fi)
        else:
            runnable.append(fi)

    runnable = rank_frontier(runnable)

    wip_remaining = max(0, wip_cap - wip_active)
    conduct_eligible: List[FrontierItem] = []
    conduct_count = 0
    for item in runnable:
        if item.adapter == AdapterCategory.CONDUCT and conduct_count < wip_remaining:
            conduct_eligible.append(item)
            conduct_count += 1

    effective_wip_active = wip_active + len(excluded_routed_ownership)
    result = FrontierResult(
        runnable=runnable,
        blocked=blocked,
        frozen=frozen_items,
        wip_cap=wip_cap,
        wip_active=effective_wip_active,
        conduct_eligible=conduct_eligible,
    )

    if emit_events:
        _emit_frontier_computed(
            conn,
            result,
            project_scope,
            wip_cap,
            effective_wip_active,
            _t0,
            session_id=session_id,
            excluded_routed_ownership=excluded_routed_ownership,
        )

    return result


def _canonical_project_label(conn: Any, project_scope: List[int]) -> str:
    """Pick the legacy single project label for event/payload surfaces."""
    if not project_scope:
        return "yoke"
    if len(project_scope) == 1:
        try:
            return resolve_project_slug(conn, int(project_scope[0]))
        except Exception:
            return str(project_scope[0])
    return "multi"


def _project_scope_labels(conn: Any, project_scope: List[int]) -> List[str]:
    labels: List[str] = []
    for project_id in project_scope:
        try:
            labels.append(resolve_project_slug(conn, int(project_id)))
        except Exception:
            labels.append(str(project_id))
    return labels


def _format_routed_ownership_reason(detail: Dict[str, Any]) -> str:
    """Render the blocked-reason string for a routed-ownership defense."""
    return (
        "Defended by routed-ownership invariant: "
        f"prior owner session {detail['prior_owner_session_id']} released "
        f"claim {detail['latest_claim_id']} with intent "
        f"{detail['release_reason_intent']} "
        f"(defense_class={detail['defense_class']}, "
        f"checkpoint_outcome={detail['checkpoint_outcome']})"
    )


_logger = logging.getLogger(__name__)


def _emit_frontier_computed(
    conn: Any,
    result: FrontierResult,
    project_scope: List[int],
    wip_cap: int,
    wip_active: int,
    t0: float,
    *,
    session_id: Optional[str] = None,
    excluded_routed_ownership: Optional[List[Dict[str, Any]]] = None,
) -> None:
    """Emit a FrontierComputed event with core-owned frontier context."""
    try:
        from .events import emit_event

        duration_ms = int((time.monotonic() - t0) * 1000)
        ranking_summary = [
            {
                "item_id": fi.item_id,
                "priority": fi.priority,
                "adapter": fi.adapter.value
                if isinstance(fi.adapter, AdapterCategory)
                else str(fi.adapter),
            }
            for fi in result.runnable[:5]
        ]

        excluded_details = list(excluded_routed_ownership or [])
        emit_event(
            "FrontierComputed",
            event_kind="workflow",
            event_type="frontier_computation",
            source_type="backend",
            session_id=session_id or "",
            duration_ms=duration_ms,
            project=_canonical_project_label(conn, project_scope),
            context={
                "project_scope": _project_scope_labels(conn, project_scope),
                "wip_cap": wip_cap,
                "wip_active": wip_active,
                "runnable_count": len(result.runnable),
                "blocked_count": len(result.blocked),
                "frozen_count": len(result.frozen),
                "conduct_eligible_count": len(result.conduct_eligible),
                "ranking_summary": ranking_summary,
                "duration_ms": duration_ms,
                "excluded_routed_ownership_count": len(excluded_details),
                "excluded_routed_ownership": excluded_details,
            },
        )
    except Exception as exc:
        _logger.debug("FrontierComputed emission failed: %s", exc)
