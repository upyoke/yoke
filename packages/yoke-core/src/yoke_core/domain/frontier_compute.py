"""Frontier computation orchestration."""

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
from .frontier_sql import (
    FRONTIER_ITEMS_SQL_PREFIX,
    FRONTIER_ITEMS_SQL_SUFFIX,
    UNBLOCKS_COUNT_SQL,
)
from .frontier_types import AdapterCategory, FrontierItem, FrontierResult
from .idea_body_completeness import (
    INCOMPLETE_REASON as _IDEA_INCOMPLETE_REASON,
    is_idea_body_incomplete,
)
from .frontier_compute_telemetry import _emit_frontier_computed
from .item_ref_resolution import remap_ref_keys_to_internal
from .project_identity import resolve_project_slug
from .project_scope import normalize_project_scope
from .project_settings import resolve_default_wip_cap
from .queries import is_blocked, is_frozen
from .runtime_settings import get_seconds
from .workflow_definition_builders import (
    IMPLEMENTATION_WORKFLOW_SKILL_IDS,
)
from .workflow_runtime import workflow_runtime_from_row
from .workflow_runtime import ENGINE_WAIT_STAGE_IDS

def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _project_scope_clause(conn: Any, project_scope: List[int]) -> str:
    """Build an ``AND i.project_id IN (...)`` clause for the scope ids."""
    if not project_scope:
        return " AND 1=0"
    placeholders = ", ".join(_p(conn) for _ in project_scope)
    return f" AND i.project_id IN ({placeholders})"


def compute_frontier(
    conn: Any,
    project_scope: List[Any],
    wip_cap: Optional[int] = None,
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
    if wip_cap is None:
        wip_cap = resolve_default_wip_cap(project_scope)
    cursor = conn.cursor()

    project_clause = _project_scope_clause(conn, project_scope)
    items_sql = FRONTIER_ITEMS_SQL_PREFIX + project_clause + FRONTIER_ITEMS_SQL_SUFFIX
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

    # Dependency edges store public text refs whose sequence may diverge
    # from the internal id; rekey every edge-derived map by internal id
    # so lookups share the scheduler's internal currency.
    hard_blocks: Dict[int, List[Tuple[str, str]]] = remap_ref_keys_to_internal(
        conn,
        {
            dep_item: [
                (d.blocking_item, d.blocking_status or "unknown")
                for d in details
            ]
            for dep_item, details in activation_blocks.items()
        },
    )
    blocker_details_map: Dict[int, List[Dict[str, Any]]] = (
        remap_ref_keys_to_internal(
            conn,
            {
                dep_item: [d.to_dict() for d in details]
                for dep_item, details in activation_blocks.items()
            },
        )
    )

    cursor.execute(UNBLOCKS_COUNT_SQL)
    unblocks_map: Dict[int, int] = remap_ref_keys_to_internal(
        conn, dict(cursor.fetchall()),
    )

    depth_map: Dict[int, int] = remap_ref_keys_to_internal(
        conn, _compute_downstream_depths(conn),
    )

    wip_active = 0
    wip_active_items: List[int] = []

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
        internal_item_id = int(item["id"])
        status = item["status"]
        workflow = workflow_runtime_from_row(item)
        adapter = classify_next_action(workflow, status)
        if adapter == AdapterCategory.SKIP:
            continue
        if (
            status in ENGINE_WAIT_STAGE_IDS
            and status != "blocked"
        ):
            continue
        stage_index = workflow.stage_index(status)
        if (
            not is_frozen(item["frozen"])
            and workflow.skill_has_started(
                status,
                IMPLEMENTATION_WORKFLOW_SKILL_IDS,
            )
        ):
            wip_active += 1
            wip_active_items.append(internal_item_id)

        fi = FrontierItem(
            item_id=internal_item_id,
            title=item["title"],
            status=status,
            priority=item["priority"],
            project=_project_label(item["project"]),
            workflow_id=workflow.workflow_id,
            workflow_version_id=workflow.workflow_version_id,
            workflow_version=workflow.version,
            stage_index=stage_index if stage_index is not None else -1,
            adapter=adapter,
            stage_count=len(workflow.stages),
            stage_label=str(
                (workflow.stage(status) or {}).get("label") or status
            ),
            probe_path_claim_activation=(
                workflow.requires_item_path_claim_probe(status)
            ),
            unblocks_count=unblocks_map.get(internal_item_id, 0),
            downstream_depth=depth_map.get(internal_item_id, 0),
            created_at=item["created_at"],
        )

        if is_frozen(item["frozen"]):
            frozen_items.append(fi)
            continue

        blockers = hard_blocks.get(internal_item_id, [])
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
            fi.blocker_details = blocker_details_map.get(internal_item_id, [])

        idea_incomplete = (
            status == workflow.stage_ids[0]
            and is_idea_body_incomplete(item)
        )
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
        elif internal_item_id in defended_items:
            fi.adapter = AdapterCategory.WAIT
            detail = defended_items[internal_item_id]
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

    wip_active_items.extend(sorted(excluded_routed_ownership))
    effective_wip_active = wip_active + len(excluded_routed_ownership)
    result = FrontierResult(
        runnable=runnable,
        blocked=blocked,
        frozen=frozen_items,
        wip_cap=wip_cap,
        wip_active=effective_wip_active,
        wip_active_items=wip_active_items,
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
