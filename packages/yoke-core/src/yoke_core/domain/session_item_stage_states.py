"""Pinned-workflow stage states for the primary item on a session card.

The strip paints one segment per stage of the item's pinned workflow
version. Which segment is active comes from the item status and the live
work claim together: a skill binding's ``from_stage_id`` is the handoff the
previous skill completed, so once the session holding the item's claim is
working in that binding's own skill mode, the handoff stage is done and the
binding's first working stage is the active one. A Dash at status ``idea``
under a claim held in ``dash`` mode therefore shows ``idea`` complete and
``implementing`` active; the same Dash unclaimed, or claimed by a session
still waiting, shows ``idea`` active.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_item_id
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.session_item_stage_failures import (
    launch_failures,
    merge_failures,
    qa_failures,
)
from yoke_core.domain.workflow_runtime import (
    WorkflowRuntime,
    workflow_runtime_from_row,
)
from yoke_core.domain.work_claim_targets import scope_int_sql


def _p(conn: Any) -> str:
    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def _session_ids(rows: Iterable[Mapping[str, Any]]) -> tuple[str, ...]:
    return tuple(
        dict.fromkeys(
            str(row.get("session_id") or "")
            for row in rows
            if row.get("session_id")
        )
    )


def _active_item_claims(
    conn: Any,
    session_ids: Sequence[str],
) -> dict[str, list[tuple[int, str]]]:
    required = ("work_claims", "items", "projects")
    if not session_ids or not all(_table_exists(conn, name) for name in required):
        return {}
    marker = _p(conn)
    item_id = scope_int_sql(conn, "c.scope", "item_id")
    records = conn.execute(
        f"SELECT c.session_id,{item_id} AS item_id,i.project_sequence,"
        "p.public_item_prefix FROM work_claims c JOIN items i "
        f"ON i.id={item_id} JOIN projects p ON p.id=i.project_id "
        "WHERE c.released_at IS NULL AND c.target_kind='item' "
        "AND c.session_id IN ("
        + ",".join(marker for _ in session_ids)
        + ") ORDER BY c.claimed_at DESC,c.id DESC",
        tuple(session_ids),
    ).fetchall()
    grouped: dict[str, list[tuple[int, str]]] = {}
    for record in records:
        if record["item_id"] is not None:
            grouped.setdefault(str(record["session_id"]), []).append(
                (
                    int(record["item_id"]),
                    format_item_ref(
                        None,
                        record["public_item_prefix"],
                        record["project_sequence"],
                    ),
                )
            )
    return grouped


def _focused_item_id(conn: Any, row: Mapping[str, Any]) -> int | None:
    public_ref = str(row.get("current_item") or "").strip()
    if not public_ref:
        return None
    errors = (
        LookupError,
        TypeError,
        ValueError,
        *db_backend.database_error_types(conn),
    )
    try:
        found = resolve_item_id(
            conn,
            public_ref,
            project=row.get("current_item_project_id") or row.get("project_id"),
        )
    except errors:
        return None
    return int(found) if found is not None else None


def _primary_item_ids(
    conn: Any,
    rows: list[dict[str, Any]],
) -> dict[str, int]:
    claims = _active_item_claims(conn, _session_ids(rows))
    selected: dict[str, int] = {}
    for row in rows:
        session_id = str(row.get("session_id") or "")
        held = claims.get(session_id, [])
        focused_ref = str(row.get("current_item") or "")
        focused = next(
            (item_id for item_id, public_ref in held if public_ref == focused_ref),
            None,
        )
        if focused is not None:
            selected[session_id] = focused
        elif held:
            selected[session_id] = held[0][0]
        elif row.get("work_role"):
            lane_item = _focused_item_id(conn, row)
            if lane_item is not None:
                selected[session_id] = lane_item
    return selected


def _item_rows(conn: Any, item_ids: Sequence[int]) -> dict[int, dict[str, Any]]:
    required = ("items", "workflow_versions", "projects")
    if not item_ids or not all(_table_exists(conn, name) for name in required):
        return {}
    marker = _p(conn)
    records = conn.execute(
        "SELECT i.id,i.project_id,i.project_sequence,i.status,i.blocked,"
        "i.blocked_reason,i.merged_at,i.merge_queue_landed_at,i.workflow_id,"
        "i.workflow_version_id,v.version,v.definition_json,v.definition_digest,"
        "p.public_item_prefix FROM items i JOIN workflow_versions v "
        "ON v.id=i.workflow_version_id JOIN projects p ON p.id=i.project_id "
        "WHERE i.id IN ("
        + ",".join(marker for _ in item_ids)
        + ")",
        tuple(item_ids),
    ).fetchall()
    result: dict[int, dict[str, Any]] = {}
    for record in records:
        item = dict(record)
        item["runtime"] = workflow_runtime_from_row(record)
        item["public_ref"] = format_item_ref(
            None, record["public_item_prefix"], record["project_sequence"]
        )
        result[int(record["id"])] = item
    return result


def _holder_modes(conn: Any, item_ids: Sequence[int]) -> dict[int, str]:
    """Queue posture of the session holding each item's live work claim."""
    required = ("work_claims", "harness_sessions")
    if not item_ids or not all(_table_exists(conn, name) for name in required):
        return {}
    marker = _p(conn)
    item_id = scope_int_sql(conn, "c.scope", "item_id")
    records = conn.execute(
        f"SELECT {item_id} AS item_id,s.mode FROM work_claims c "
        "JOIN harness_sessions s ON s.session_id=c.session_id "
        "WHERE c.released_at IS NULL AND c.target_kind='item' "
        f"AND {item_id} IN ("
        + ",".join(marker for _ in item_ids)
        + ") ORDER BY c.claimed_at DESC,c.id DESC",
        tuple(item_ids),
    ).fetchall()
    modes: dict[int, str] = {}
    for record in records:
        modes.setdefault(int(record["item_id"]), str(record["mode"] or ""))
    return modes


def _closeout_stage(runtime: WorkflowRuntime) -> str:
    return next(
        stage_id
        for stage_id in reversed(runtime.stage_ids)
        if stage_id not in runtime.terminal_stage_ids
    )


def active_stage_id(
    runtime: WorkflowRuntime,
    status: str,
    *,
    landed_open: bool = False,
    holder_mode: str | None = None,
) -> str:
    """The stage the strip paints active, from the pin and the live claim.

    ``holder_mode`` is the queue posture of the session holding the item's
    live work claim; ``None`` means no live claim. When that posture is the
    skill bound at the item's status and the status is that binding's
    handoff stage, the skill has taken the handoff and its first working
    stage is active. A binding with no working stage after its handoff, and
    every other posture, leave the status-derived stage active.
    """
    if landed_open:
        return _closeout_stage(runtime)
    binding = runtime.skill_binding_for_stage(status)
    if (
        binding is None
        or not holder_mode
        or str(binding["skill_id"]) != holder_mode
        or str(binding["from_stage_id"]) != status
    ):
        return status
    working = runtime.next_stage_id(status)
    if working is None or working == str(binding["through_stage_id"]):
        return status
    return working


def item_stage_states(
    runtime: WorkflowRuntime,
    status: str,
    *,
    landed_open: bool = False,
    failures: Mapping[str, str] | None = None,
    holder_mode: str | None = None,
) -> list[dict[str, Any]]:
    """Classify every pinned stage from ordered workflow and live item facts."""
    active_stage = active_stage_id(
        runtime, status, landed_open=landed_open, holder_mode=holder_mode
    )
    active_index = runtime.stage_index(active_stage)
    if active_index is None:
        active_index = 0
    # A gate recorded against a stage guards entry into it, so its failure
    # belongs to the stage the item is trying to leave. A failure on a stage
    # already passed stays there; one it has not entered is never painted.
    placed: dict[int, str] = {}
    for stage_id, failure in (failures or {}).items():
        stage_position = runtime.stage_index(stage_id)
        if stage_position is None or stage_position > active_index:
            stage_position = active_index
        placed[stage_position] = failure
    result = []
    for index, stage_id in enumerate(runtime.stage_ids):
        state = "complete" if index < active_index else "pending"
        if index == active_index:
            state = "active"
        failure = placed.get(index)
        if failure:
            state = "failed"
        result.append(
            {
                "name": runtime.stage_label(stage_id),
                "state": state,
                "failure": failure or None,
            }
        )
    return result


def primary_item_stages_by_session(
    conn: Any, rows: list[dict[str, Any]],
) -> dict[str, list[dict[str, Any]]]:
    """Project the primary held item's stage strip for each roster session."""
    selected = _primary_item_ids(conn, rows)
    items = _item_rows(conn, tuple(dict.fromkeys(selected.values())))
    item_ids = tuple(items)
    qa = qa_failures(conn, item_ids)
    merge = merge_failures(conn, item_ids)
    launch = launch_failures(conn, items)
    holder_modes = _holder_modes(conn, item_ids)
    projected: dict[str, list[dict[str, Any]]] = {}
    for session_id, item_id in selected.items():
        item = items.get(item_id)
        if item is None:
            continue
        runtime = item["runtime"]
        status = str(item["status"] or "")
        landed_open = bool(
            status not in runtime.terminal_stage_ids
            and (item.get("merged_at") or item.get("merge_queue_landed_at"))
        )
        holder_mode = holder_modes.get(item_id)
        active_stage = active_stage_id(
            runtime, status, landed_open=landed_open, holder_mode=holder_mode
        )
        failures: dict[str, str] = {}
        if item_id in launch:
            failures[active_stage] = launch[item_id]
        if item_id in qa:
            failures[qa[item_id]] = "QA failed"
        if item_id in merge:
            failures[_closeout_stage(runtime)] = merge[item_id]
        if int(item.get("blocked") or 0):
            reason = str(item.get("blocked_reason") or "reason not recorded")
            failures[active_stage] = f"blocked: {reason}"
        projected[session_id] = item_stage_states(
            runtime,
            status,
            landed_open=landed_open,
            failures=failures,
            holder_mode=holder_mode,
        )
    return projected


__all__ = [
    "active_stage_id",
    "item_stage_states",
    "primary_item_stages_by_session",
]
