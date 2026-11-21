"""Membership and recovery for Dash delivery without a merge to attribute."""

from __future__ import annotations

from shlex import quote
from typing import Any

from yoke_core.domain.dash_posture_read import marker, posture
from yoke_core.domain.deployment_item_completion_runs import completion_runs_for_items
from yoke_core.domain.deployment_item_flow_resolution import item_completion_flows
from yoke_core.domain.deployment_run_member_targeting import supplemental_run_ids
from yoke_core.domain.item_json_sections import read_json_sections
from yoke_core.domain.item_ref_render import render_item_ref_lookup
from yoke_core.domain.schema_common import _column_exists, _table_exists
from yoke_core.domain.workflow_behavior import delivery_redirect_stage
from yoke_core.domain.workflow_item_binding_validation import read_pinned_items


def _release_waits(conn: Any, scope: str, params: tuple) -> dict[int, tuple[int, str]]:
    """Project identity for Dashes with a recorded finding and selected posture."""
    from yoke_core.domain.dash_execution import DASH_EVIDENCE_SECTION

    if not _table_exists(conn, "item_sections") or not _column_exists(
        conn, "items", "workflow_posture"
    ):
        return {}
    rows = conn.execute(
        "SELECT i.id, i.project_id, p.slug, i.workflow_posture "
        "FROM items i JOIN projects p ON p.id=i.project_id "
        f"WHERE i.workflow_id='dash' AND {scope}",
        params,
    ).fetchall()
    selected = {
        int(row[0]): (int(row[1]), str(row[2]))
        for row in rows
        if posture({"workflow_posture": row[3]}).get("deployment") is True
    }
    evidence = read_json_sections(
        conn, item_ids=selected, section=DASH_EVIDENCE_SECTION
    )
    findings = [
        item_id
        for item_id, record in evidence.items()
        if record.get("no_changes") is True and not record.get("merge_sha")
    ]
    return {
        item_id: selected[item_id]
        for item_id, item in read_pinned_items(conn, findings).items()
        if item.runtime and item.status == delivery_redirect_stage(item.runtime)
    }


def enrollment_candidates(
    conn: Any, *, project_id: int, flow: str, item_ids: tuple[int, ...] | None = None
) -> set[int]:
    """Waiting items of this flow without another release delivering them."""
    p = marker(conn)
    scope, params = f"i.project_id={p}", (project_id,)
    if item_ids is not None:
        if not item_ids:
            return set()
        slots = ",".join(p for _ in item_ids)
        scope += f" AND i.id IN ({slots})"
        params += item_ids
    waiting = _release_waits(conn, scope, params)
    matching = [
        item_id
        for item_id, selected_flow in item_completion_flows(conn, waiting).items()
        if selected_flow == flow
    ]
    return {
        item_id
        for item_id, runs in completion_runs_for_items(conn, matching).items()
        if not any(
            run["status"] in {"created", "executing", "succeeded"} for run in runs
        )
    }


def _open_run(conn: Any, project_id: int, flow: str) -> str:
    p = marker(conn)
    rows = conn.execute(
        f"SELECT id FROM deployment_runs WHERE project_id={p} AND flow={p} "
        "AND status='created' AND composition_frozen_at IS NULL "
        "ORDER BY created_at DESC, id DESC",
        (project_id, flow),
    ).fetchall()
    runs = [str(row[0]) for row in rows]
    supplemental = supplemental_run_ids(conn, run_ids=runs, completion_flow=flow)
    return next((run for run in runs if run not in supplemental), "")


def _recovery(ref: str, project: str, flow: str, run: str) -> tuple[str, str]:
    message = f"No completion run lists {ref}, which recorded a no-change finding."
    if run:
        hint = f"Enroll it: `yoke deployment-runs add-item {quote(run)} {quote(ref)}`."
    elif flow:
        hint = (
            "Create a run to enroll it: `yoke deployment-runs create "
            f'{quote(project)} {quote(flow)} --idempotency-key "$(uuidgen)"`.'
        )
    else:
        hint = f"Select a deployment flow for {ref}, then create a run of that flow."
    return message, hint


def missing_membership_recoveries(
    conn: Any, item_ids: tuple[int, ...]
) -> dict[int, tuple[str, str]]:
    """The shared lifecycle and next-action answer for an unenrolled finding."""
    if not item_ids:
        return {}
    p = marker(conn)
    slots = ",".join(p for _ in item_ids)
    waiting = _release_waits(conn, f"i.id IN ({slots})", item_ids)
    missing = [
        item_id
        for item_id, runs in completion_runs_for_items(conn, waiting).items()
        if not runs
    ]
    if not missing:
        return {}
    flows = item_completion_flows(conn, missing)
    keys = {(waiting[item_id][0], flow) for item_id, flow in flows.items() if flow}
    open_runs = {(pid, flow): _open_run(conn, pid, flow) for pid, flow in sorted(keys)}
    refs = render_item_ref_lookup(conn, missing)
    return {
        item_id: _recovery(
            refs(item_id),
            waiting[item_id][1],
            flows.get(item_id, ""),
            open_runs.get((waiting[item_id][0], flows.get(item_id, "")), ""),
        )
        for item_id in missing
    }
