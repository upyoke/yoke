"""QA test execution and run management.

Parent shim for the QA-execution surface. Owns ``cmd_run_add``,
``cmd_run_complete``, ``cmd_run_list``, and ``cmd_run_get``. Other
execution-domain commands live in dedicated sibling modules
(``qa_run_batch``, ``qa_artifact_ops``, ``qa_evidence_bridge``) and are
re-exported here so existing callers keep working unchanged. Event
helpers come from ``qa_events``; vocab/formatting helpers from
``qa_constants``.
"""

from __future__ import annotations

import os
import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import (
    connect,
    iso8601_now,
    query_one,
    query_rows,
    query_scalar,
)
from yoke_core.domain.qa_constants import (  # noqa: F401  (re-exported)
    VALID_BROWSER_QA_KINDS,
    _coalesce,
    _normalize_qa_kind,
    _pipe_row,
)
from yoke_core.domain import qa_events
from yoke_core.domain.qa_artifact_ops import (  # noqa: F401  (re-exported)
    _ART_SELECT,
    cmd_artifact_add,
    cmd_artifact_list,
    linked_artifact_handle,
)
from yoke_core.domain.qa_run_batch import cmd_run_add_batch  # noqa: F401  (re-exported)
from yoke_core.domain.qa_evidence_bridge import (  # noqa: F401  (re-exported)
    cmd_satisfy_screenshot_evidence,
)


# Backward-compat aliases for the parent shim's existing API. Internal
# callers (and qa.py re-exports) reference the underscore-prefixed names;
# the leaf modules expose canonical public names.
_resolve_requirement_event_target = qa_events.resolve_requirement_event_target
_emit_qa_requirement_event = qa_events.emit_qa_requirement_event
_emit_qa_run_event = qa_events.emit_qa_run_event
_linked_artifact_handle = linked_artifact_handle


_RUN_SELECT = (
    "id, qa_requirement_id, executor_type, qa_kind, COALESCE(verdict,''), "
    "COALESCE(CAST(score AS TEXT),''), COALESCE(CAST(confidence AS TEXT),''), "
    "COALESCE(raw_result,''), COALESCE(CAST(duration_ms AS TEXT),''), "
    "COALESCE(started_at,''), COALESCE(completed_at,''), created_at"
)


def _resolve_qa_kind(
    db_path: Optional[str], requirement_id: int, qa_kind: Optional[str],
) -> str:
    """Derive qa_kind from the requirement; reject mismatches."""
    _peek = connect(path=db_path)
    try:
        stored = query_scalar(
            _peek, "SELECT qa_kind FROM qa_requirements WHERE id = %s",
            (requirement_id,),
        )
    finally:
        _peek.close()
    if not stored:
        print(f"Error: requirement_id {requirement_id} not found in "
              "qa_requirements", file=sys.stderr)
        sys.exit(2)
    canonical = _normalize_qa_kind(str(stored))
    if not qa_kind:
        return canonical
    supplied = _normalize_qa_kind(qa_kind)
    if supplied != canonical:
        print(f"Error: --qa-kind '{supplied}' does not match the "
              f"requirement's stored kind '{canonical}'. Omit --qa-kind "
              "to use the requirement's kind, or fix the argument.",
              file=sys.stderr)
        sys.exit(2)
    return supplied


def cmd_run_add(
    *,
    db_path: Optional[str] = None,
    requirement_id: int,
    executor_type: str,
    qa_kind: Optional[str] = None,
    verdict: Optional[str] = None,
    execution_status: Optional[str] = None,
    score: Optional[float] = None,
    confidence: Optional[float] = None,
    raw_result: Optional[str] = None,
    duration_ms: Optional[int] = None,
    artifact_path: Optional[str] = None,
) -> int:
    """Insert a qa_run row. Returns the new ID. ``qa_kind`` defaults to
    the requirement's stored kind; a supplied mismatch is a hard error."""
    if not requirement_id:
        print("Error: --requirement-id is required", file=sys.stderr)
        sys.exit(2)
    if not executor_type:
        print("Error: --executor-type is required", file=sys.stderr)
        sys.exit(2)
    qa_kind = _resolve_qa_kind(db_path, requirement_id, qa_kind)

    # Reject agent executor for browser QA kinds
    if executor_type == "agent":
        if qa_kind in VALID_BROWSER_QA_KINDS:
            print(f"Error: executor_type 'agent' is not allowed for qa_kind '{qa_kind}' -- use browser_substrate", file=sys.stderr)
            sys.exit(2)

    conn = connect(path=db_path)
    try:
        # Reject agent executor for ac_verification with screenshot evidence
        if executor_type == "agent" and qa_kind == "ac_verification":
            req_policy = query_scalar(
                conn,
                "SELECT success_policy FROM qa_requirements WHERE id = %s",
                (requirement_id,),
            )
            if req_policy and "requires_screenshot_evidence" in str(req_policy):
                print(
                    "Error: executor_type 'agent' is not allowed for ac_verification "
                    "with [requires_screenshot_evidence] -- use browser_substrate",
                    file=sys.stderr,
                )
                sys.exit(2)

        # Epic-task implementation-review runs must flow through yoke-db epic review-insert
        if qa_kind == "implementation_review":
            target_row = query_one(
                conn,
                "SELECT COALESCE(CAST(item_id AS TEXT), '') AS item_id, COALESCE(CAST(epic_id AS TEXT), '') AS epic_id, COALESCE(CAST(task_num AS TEXT), '') AS task_num FROM qa_requirements WHERE id = %s",
                (requirement_id,),
            )
            if target_row:
                t_item = str(target_row["item_id"])
                t_epic = str(target_row["epic_id"])
                t_task = str(target_row["task_num"])
                if not t_item and t_epic and t_task:
                    if os.environ.get("YOKE_INTERNAL_EPIC_REVIEW_WRITE") != "1":
                        print(
                            "Error: epic-task qa_kind 'implementation_review' runs must use db_router epic review-insert.",
                            file=sys.stderr,
                        )
                        sys.exit(2)

        now_iso = iso8601_now()
        # a row is "completed" when either a verdict or a capture
        # execution_status lands (both mark the run as finalized in some
        # dimension). Pure QARunStarted rows stay with completed_at=NULL.
        completed_at_value = (
            now_iso if (verdict is not None or execution_status is not None) else None
        )

        sql = """INSERT INTO qa_runs
                  (qa_requirement_id, executor_type, qa_kind, verdict,
                   execution_status, score, confidence, raw_result,
                   duration_ms, started_at, completed_at, created_at)
                  VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"""
        cur = conn.execute(sql, (
            requirement_id, executor_type, qa_kind, verdict,
            execution_status, score, confidence, raw_result, duration_ms,
            now_iso, completed_at_value, now_iso,
        ))
        inserted_id = int(cur.fetchone()[0])
        from yoke_core.domain.item_activity import touch_for_qa_requirement
        touch_for_qa_requirement(conn, requirement_id)  # R1 item activity
        conn.commit()
        if verdict is not None:
            _event_name = "QARunCompleted"
        elif execution_status is not None:
            _event_name = "QARunCaptured"
        else:
            _event_name = "QARunStarted"
        qa_events.emit_qa_run_event(
            conn,
            db_path=db_path,
            event_name=_event_name,
            run_id=inserted_id,
            requirement_id=requirement_id,
            qa_kind=qa_kind,
            verdict=verdict,
        )
        # optional one-step artifact creation
        if artifact_path is not None:
            _ext = os.path.splitext(artifact_path)[1].lower()
            _content_type = {
                ".png": "image/png",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".webp": "image/webp",
                ".gif": "image/gif",
            }.get(_ext, "application/octet-stream")
            _handle = linked_artifact_handle(
                conn,
                requirement_id=requirement_id,
                run_id=inserted_id,
                artifact_path=artifact_path,
            )
            conn.execute(
                """INSERT INTO qa_artifacts (qa_run_id, artifact_type, content_type, artifact_handle, metadata, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s)""",
                (inserted_id, "screenshot", _content_type, _handle, None, iso8601_now()),
            )
            conn.commit()
    finally:
        conn.close()

    print(inserted_id)
    return inserted_id


def cmd_run_complete(
    *,
    db_path: Optional[str] = None,
    run_id: int,
    verdict: Optional[str] = None,
    execution_status: Optional[str] = None,
    raw_result: Optional[str] = None,
    duration_ms: Optional[int] = None,
) -> int:
    """Finalize an in-progress run. Returns the run ID.

    browser capture can finalize with ``execution_status='captured'``
    and ``verdict=None`` — the infra step succeeded but quality has not been
    inspected yet. Inspection is a later ``run-complete`` call that sets
    ``verdict='pass'`` or ``verdict='fail'`` in place. At least one of
    ``verdict`` or ``execution_status`` must be provided.

    Event emission: ``QARunCompleted`` fires when a verdict is written,
    ``QARunCaptured`` when only an execution_status is written (capture
    finalized but awaiting inspection).
    """
    if not run_id:
        print("Error: --run-id is required", file=sys.stderr)
        sys.exit(2)
    if verdict is None and execution_status is None:
        print(
            "Error: at least one of --verdict or --execution-status is required",
            file=sys.stderr,
        )
        sys.exit(2)

    conn = connect(path=db_path)
    try:
        # Verify the run exists
        row = query_one(conn, "SELECT qa_requirement_id, executor_type, qa_kind FROM qa_runs WHERE id = %s", (run_id,))
        if row is None:
            print(f"Error: run {run_id} not found", file=sys.stderr)
            sys.exit(1)

        params: list = [iso8601_now()]
        set_parts = ["completed_at = %s"]
        if verdict is not None:
            set_parts.append("verdict = %s")
            params.append(verdict)
        if execution_status is not None:
            set_parts.append("execution_status = %s")
            params.append(execution_status)
        if raw_result is not None:
            set_parts.append("raw_result = %s")
            params.append(raw_result)
        if duration_ms is not None:
            set_parts.append("duration_ms = %s")
            params.append(duration_ms)

        params.append(run_id)
        conn.execute(f"UPDATE qa_runs SET {', '.join(set_parts)} WHERE id = %s", tuple(params))
        conn.commit()

        if verdict is not None:
            check = query_scalar(conn, "SELECT verdict FROM qa_runs WHERE id = %s", (run_id,))
            if check != verdict:
                print(f"Error: run {run_id} update failed", file=sys.stderr)
                sys.exit(1)
        event_name = "QARunCompleted" if verdict is not None else "QARunCaptured"
        qa_events.emit_qa_run_event(
            conn,
            db_path=db_path,
            event_name=event_name,
            run_id=run_id,
            requirement_id=int(row["qa_requirement_id"]),
            qa_kind=str(row["qa_kind"]),
            verdict=verdict,
        )
    finally:
        conn.close()

    print(run_id)
    return run_id


def cmd_run_list(
    *,
    db_path: Optional[str] = None,
    requirement_id: Optional[int] = None,
) -> List[str]:
    """List runs (pipe-delimited). Returns list of formatted lines."""
    conn = connect(path=db_path)
    try:
        where = "1=1"
        params: tuple = ()
        if requirement_id is not None:
            where = "qa_requirement_id = %s"
            params = (requirement_id,)

        rows = query_rows(conn, f"SELECT {_RUN_SELECT} FROM qa_runs WHERE {where} ORDER BY id", params)
    finally:
        conn.close()

    lines = []
    for row in rows:
        line = _pipe_row(row)
        print(line)
        lines.append(line)
    return lines


def cmd_run_get(
    run_id: int,
    *,
    db_path: Optional[str] = None,
) -> str:
    """Get a single run (pipe-delimited). Returns the formatted line."""
    if run_id is None:
        print("Usage: qa run-get <id>", file=sys.stderr)
        sys.exit(2)

    conn = connect(path=db_path)
    try:
        row = query_one(conn, f"SELECT {_RUN_SELECT} FROM qa_runs WHERE id = %s", (run_id,))
    finally:
        conn.close()

    if row is None:
        print(f"Error: run {run_id} not found", file=sys.stderr)
        sys.exit(1)

    line = _pipe_row(row)
    print(line)
    return line
