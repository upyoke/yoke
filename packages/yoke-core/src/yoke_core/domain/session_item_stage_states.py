"""Pinned-workflow stage states for the primary item on a session card."""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

from yoke_contracts.public_ref import format_item_ref
from yoke_core.domain import db_backend
from yoke_core.domain.project_identity import resolve_item_id
from yoke_core.domain.qa_constants import VALID_VERDICTS
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_runtime import (
    WorkflowRuntime,
    workflow_runtime_from_row,
)
from yoke_core.domain.work_claim_targets import scope_int_sql


_FAIL_VERDICTS = tuple(
    verdict for verdict in VALID_VERDICTS if verdict in {"fail", "error"}
)
_LAUNCH_FAILURE_STATES = frozenset({"expired", "failed", "outcome_unknown"})
_MERGE_FAILURE_LABELS = {
    "MergePullRequestCiFailed": "CI checks failed",
    "MergeBlockedNoVerificationEvidence": "verification missing",
}
_MERGE_FAILURE_EVENTS = frozenset(
    {
        *_MERGE_FAILURE_LABELS,
        "MergeBranchPushFailed",
        "MergeEngineFailed",
        "MergePullRequestCreateFailed",
        "MergePullRequestMergeFailed",
        "MergeTargetPushFailed",
        "MergeTargetStale",
        "MergeVerificationFailed",
    }
)
_MERGE_SUCCESS_EVENTS = frozenset(
    {
        "MergeEngineSucceeded",
        "MergePullRequestCiPassed",
        "MergeVerificationPassed",
    }
)


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


def _qa_failures(conn: Any, item_ids: Sequence[int]) -> dict[int, str]:
    if not item_ids or not all(
        _table_exists(conn, name) for name in ("qa_requirements", "qa_runs")
    ):
        return {}
    marker = _p(conn)
    fail_markers = ",".join(marker for _ in _FAIL_VERDICTS)
    records = conn.execute(
        "SELECT item_id,workflow_transition_id,run_id FROM ("
        "SELECT q.item_id,q.workflow_transition_id,r.id AS run_id,r.verdict,"
        "ROW_NUMBER() OVER (PARTITION BY q.id ORDER BY r.id DESC) AS row_num "
        "FROM qa_requirements q JOIN qa_runs r ON r.qa_requirement_id=q.id "
        "WHERE q.item_id IN ("
        + ",".join(marker for _ in item_ids)
        + ")) latest WHERE row_num=1 AND verdict IN ("
        + fail_markers
        + ") ORDER BY run_id DESC",
        (*item_ids, *_FAIL_VERDICTS),
    ).fetchall()
    failures: dict[int, str] = {}
    for record in records:
        failures.setdefault(
            int(record["item_id"]),
            str(record["workflow_transition_id"] or ""),
        )
    return failures


def _merge_failures(conn: Any, item_ids: Sequence[int]) -> dict[int, str]:
    if not item_ids or not _table_exists(conn, "events"):
        return {}
    marker = _p(conn)
    names = tuple(sorted(_MERGE_FAILURE_EVENTS | _MERGE_SUCCESS_EVENTS))
    records = conn.execute(
        "SELECT item_id,event_name FROM events WHERE item_id IN ("
        + ",".join(marker for _ in item_ids)
        + ") AND event_name IN ("
        + ",".join(marker for _ in names)
        + ") ORDER BY created_at DESC,id DESC",
        tuple(str(item_id) for item_id in item_ids) + names,
    ).fetchall()
    failures: dict[int, str] = {}
    settled: set[int] = set()
    for record in records:
        item_id = int(record["item_id"])
        if item_id in settled:
            continue
        name = str(record["event_name"])
        if name in _MERGE_SUCCESS_EVENTS:
            settled.add(item_id)
        else:
            failures[item_id] = _MERGE_FAILURE_LABELS.get(
                name, "merge failed"
            )
            settled.add(item_id)
    return failures


def _launch_failures(
    conn: Any, items: Mapping[int, Mapping[str, Any]],
) -> dict[int, str]:
    if not items or not _table_exists(conn, "session_launches"):
        return {}
    project_ids = tuple(
        dict.fromkeys(int(item["project_id"]) for item in items.values())
    )
    marker = _p(conn)
    records = conn.execute(
        "SELECT project_id,session_name,state FROM session_launches "
        "WHERE project_id IN ("
        + ",".join(marker for _ in project_ids)
        + ") ORDER BY created_at DESC,launch_id DESC",
        project_ids,
    ).fetchall()
    by_ref = {
        (int(item["project_id"]), str(item["public_ref"])): item_id
        for item_id, item in items.items()
    }
    observed: set[int] = set()
    failures: dict[int, str] = {}
    for record in records:
        public_ref = str(record["session_name"] or "").partition(":")[0]
        item_id = by_ref.get((int(record["project_id"]), public_ref))
        if item_id is None or item_id in observed:
            continue
        observed.add(item_id)
        if str(record["state"] or "") in _LAUNCH_FAILURE_STATES:
            failures[item_id] = "launch failed"
    return failures


def _closeout_stage(runtime: WorkflowRuntime) -> str:
    return next(
        stage_id
        for stage_id in reversed(runtime.stage_ids)
        if stage_id not in runtime.terminal_stage_ids
    )


def item_stage_states(
    runtime: WorkflowRuntime,
    status: str,
    *,
    landed_open: bool = False,
    failures: Mapping[str, str] | None = None,
) -> list[dict[str, Any]]:
    """Classify every pinned stage from ordered workflow and live item facts."""
    active_stage = _closeout_stage(runtime) if landed_open else status
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
    qa = _qa_failures(conn, item_ids)
    merge = _merge_failures(conn, item_ids)
    launch = _launch_failures(conn, items)
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
        active_stage = _closeout_stage(runtime) if landed_open else status
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
        )
    return projected


__all__ = ["item_stage_states", "primary_item_stages_by_session"]
