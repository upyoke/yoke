"""Typed session recipient resolution over authoritative claims."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

from yoke_contracts.session_control.models import RecipientSelector
from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_project_slug
from yoke_core.domain.session_message_anchors import anchor_hits
from yoke_core.domain.session_message_liveness import (
    applied_liveness,
    is_bulk_evidence,
    narrows_bulk_by_default,
)
from yoke_core.domain.session_message_routing import messageability, session_liveness
from yoke_core.domain.session_relay_machine_versions import (
    connected_relay_routes,
    machine_surface_versions,
)
from yoke_core.domain.work_claim_targets import scope_int_sql, scope_text_sql
from yoke_core.domain.session_message_types import (
    ResolvedRecipient,
    row_dict,
    utc_now,
)


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _session_rows(conn: Any) -> dict[str, dict[str, Any]]:
    rows = conn.execute(
        "SELECT session_id, project_id, executor, executor_surface, "
        "executor_version, machine_id, execution_lane, last_heartbeat, "
        "last_tool_call_at, ended_at, terminated_at FROM harness_sessions ORDER BY session_id"
    ).fetchall()
    return {str(row["session_id"]): row_dict(row) for row in rows}


def _claim_rows(conn: Any) -> list[dict[str, Any]]:
    item_id = scope_int_sql(conn, "wc.scope", "item_id")
    epic_id = scope_int_sql(conn, "wc.scope", "epic_id")
    task_num = scope_int_sql(conn, "wc.scope", "task_num")
    project_id = scope_int_sql(conn, "wc.scope", "project_id")
    process_key = scope_text_sql(conn, "wc.scope", "process_key")
    rows = conn.execute(
        f"SELECT wc.session_id, wc.target_kind, {item_id} AS item_id, "
        f"{epic_id} AS epic_id, {task_num} AS task_num, "
        f"{process_key} AS process_key, "
        f"COALESCE(item.project_id, epic.project_id, {project_id}, "
        "hs.project_id) "
        "AS anchor_project_id, "
        "COALESCE(task_lane.lane_role, item_lane.lane_role, '') AS work_role, "
        "COALESCE(task_lane.branch, item_lane.branch, '') AS worktree_branch, "
        "COALESCE(task_lane.path, item_lane.path, '') AS worktree_path "
        "FROM work_claims wc "
        "JOIN harness_sessions hs ON hs.session_id=wc.session_id "
        f"LEFT JOIN items item ON wc.target_kind='item' AND item.id={item_id} "
        f"LEFT JOIN items epic ON wc.target_kind='epic_task' AND epic.id={epic_id} "
        "LEFT JOIN epic_tasks et ON wc.target_kind='epic_task' "
        f"AND et.epic_id={epic_id} AND et.task_num={task_num} "
        "LEFT JOIN item_worktrees task_lane ON task_lane.id=et.item_worktree_id "
        "AND task_lane.state='active' "
        "LEFT JOIN item_worktrees item_lane ON item_lane.id=("
        f"SELECT iw.id FROM item_worktrees iw WHERE iw.item_id={item_id} "
        "AND wc.target_kind='item' AND iw.state='active' "
        "ORDER BY iw.id LIMIT 1) "
        "WHERE wc.released_at IS NULL ORDER BY wc.claimed_at, wc.id"
    ).fetchall()
    return [row_dict(row) for row in rows]


def _claim_metadata(
    claims: list[dict[str, Any]], session_id: str
) -> tuple[set[str], set[str]]:
    roles: set[str] = set()
    lanes: set[str] = set()
    for claim in claims:
        if str(claim["session_id"]) != session_id:
            continue
        if claim.get("work_role"):
            roles.add(str(claim["work_role"]))
        for key in ("worktree_branch", "worktree_path"):
            value = str(claim.get(key) or "")
            if value:
                lanes.add(value)
                lanes.add(Path(value).name)
    return roles, lanes


def _passes_filters(
    selector: RecipientSelector,
    recipient: ResolvedRecipient,
    *,
    explicit_liveness: tuple[str, ...] = (),
    bulk_liveness: tuple[str, ...] = (),
) -> bool:
    checks = (
        (selector.executor_families, {recipient.executor}),
        (selector.executor_surfaces, {recipient.executor_surface or ""}),
        (selector.work_roles, recipient.work_roles),
        (selector.execution_lanes, {recipient.execution_lane}),
        (selector.worktree_lanes, recipient.worktree_lanes),
        (selector.machine_ids, {recipient.machine_id or ""}),
        # Expanded, so the ``all`` sentinel widens instead of matching nothing.
        (explicit_liveness, {recipient.liveness}),
    )
    if not all(
        not requested or bool(set(requested) & available)
        for requested, available in checks
    ):
        return False
    # The bulk default narrows only recipients that a population anchor
    # reached. A session the sender named, or an item/epic-task/process
    # anchor resolved to, was chosen deliberately and keeps every state.
    if bulk_liveness and is_bulk_evidence(recipient.resolution):
        return recipient.liveness in bulk_liveness
    return True


def resolve_recipients(
    conn: Any,
    selector: RecipientSelector,
    *,
    now: datetime | None = None,
    steering_target: Mapping[str, Any] | None = None,
) -> list[ResolvedRecipient]:
    """Resolve unioned anchors, then intersect filters and deduplicate.

    A bulk anchor the sender did not qualify resolves against active
    sessions only; see :mod:`yoke_core.domain.session_message_liveness`.
    ``steering_target`` is the addressed work a role anchor resolves
    against; the role resolves to nobody when no live seat covers it, which
    the send path parks rather than refuses.
    """
    current = now or utc_now()
    narrows_by_default = narrows_bulk_by_default(selector)
    states = applied_liveness(selector)
    explicit_liveness = () if narrows_by_default or not selector.liveness else states
    bulk_liveness = states if narrows_by_default else ()
    sessions = _session_rows(conn)
    claims = _claim_rows(conn)
    hits = anchor_hits(
        conn, selector, sessions, claims, steering_target=steering_target
    )
    relay_routes = connected_relay_routes(conn, now=current)
    excluded = set(selector.exclude_session_ids)
    resolved: list[ResolvedRecipient] = []
    for session_id in sorted(hits):
        if session_id in excluded or session_id not in sessions:
            continue
        row = sessions[session_id]
        projects = {project_id for _evidence, project_id in hits[session_id]}
        session_project = int(row["project_id"])
        primary_project = (
            session_project if session_project in projects else min(projects)
        )
        liveness = session_liveness(row, now=current)
        roles, worktree_lanes = _claim_metadata(claims, session_id)
        recipient = ResolvedRecipient(
            session_id=session_id,
            project_id=primary_project,
            project=resolve_project_slug(conn, primary_project),
            executor=str(row.get("executor") or ""),
            executor_surface=str(row.get("executor_surface") or "") or None,
            executor_version=str(row.get("executor_version") or "") or None,
            machine_id=str(row.get("machine_id") or "") or None,
            liveness=liveness,
            messageability=messageability(
                row,
                liveness=liveness,
                machine_surface_versions=machine_surface_versions(
                    relay_routes,
                    machine_id=row.get("machine_id"),
                    project_id=row.get("project_id"),
                ),
            ),
            resolution=[evidence for evidence, _project in hits[session_id]],
            authorized_project_ids=projects,
            work_roles=roles,
            worktree_lanes=worktree_lanes,
            execution_lane=str(row.get("execution_lane") or ""),
        )
        if _passes_filters(
            selector,
            recipient,
            explicit_liveness=explicit_liveness,
            bulk_liveness=bulk_liveness,
        ):
            resolved.append(recipient)
    return resolved


def confirmation_token(
    selector: RecipientSelector,
    recipients: list[ResolvedRecipient],
    *,
    actor_recipients: list[Any] | None = None,
) -> str:
    payload = {
        "selector": selector.model_dump(mode="json"),
        "recipients": [
            [recipient.session_id, sorted(recipient.authorized_project_ids)]
            for recipient in recipients
        ],
        "actor_recipients": [
            [recipient.actor_id, sorted(recipient.shared_org_ids)]
            for recipient in actor_recipients or []
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


__all__ = ["applied_liveness", "confirmation_token", "resolve_recipients"]
