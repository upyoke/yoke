"""QA batch run insertion.

Owns ``cmd_run_add_batch`` — the JSON-driven multi-row run insertion path.
Keeping this command in its own module groups the batch-specific validation,
transaction, and per-row event emission together.

This module imports ``VALID_BROWSER_QA_KINDS`` and ``_normalize_qa_kind``
from :mod:`yoke_core.domain.qa_constants` (the leaf vocabulary module)
and ``emit_qa_run_event`` from :mod:`yoke_core.domain.qa_events` (the
leaf events module) — never from the parent ``qa_execution`` shim. That
discipline breaks the would-be import cycle that would otherwise occur
when ``qa_execution`` re-exports ``cmd_run_add_batch`` from this module.
"""

from __future__ import annotations

import json
import os
import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import (
    connect,
    iso8601_now,
    query_one,
    query_scalar,
)
from yoke_core.domain.qa_artifact_handle import (
    local_handle,
    serialize_handle,
)
from yoke_core.domain.qa_constants import (
    VALID_BROWSER_QA_KINDS,
    _normalize_qa_kind,
)
from yoke_core.domain.qa_events import emit_qa_run_event


def cmd_run_add_batch(
    *,
    db_path: Optional[str] = None,
    json_file: str,
) -> List[int]:
    """Insert multiple qa_run rows in one transaction. Returns list of new IDs.

    The JSON file must contain an array of objects with the same fields as
    run-add: requirement_id, executor_type, qa_kind, verdict, score,
    confidence, raw_result, duration_ms, artifact_path.

    Rolls back the entire batch if any row fails validation.
    Emits per-row QA lifecycle events.
    """
    # Read and parse JSON file
    try:
        with open(json_file, "r") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: cannot read/parse --json-file: {exc}", file=sys.stderr)
        sys.exit(2)

    if not isinstance(payload, list):
        print("Error: --json-file must contain a JSON array", file=sys.stderr)
        sys.exit(2)

    if len(payload) == 0:
        print("Error: --json-file array is empty", file=sys.stderr)
        sys.exit(2)

    # Pre-validate every row. ``qa_kind`` is optional per row when the
    # caller wants the value derived from the requirement; mismatches
    # between a supplied ``qa_kind`` and the requirement's stored value
    # are caught below in the DB-aware pass.
    for idx, row in enumerate(payload):
        if not isinstance(row, dict):
            print(f"Error: row {idx} is not an object", file=sys.stderr)
            sys.exit(2)

        if not row.get("requirement_id"):
            print(f"Error: row {idx} missing required field 'requirement_id'", file=sys.stderr)
            sys.exit(2)
        if not row.get("executor_type"):
            print(f"Error: row {idx} missing required field 'executor_type'", file=sys.stderr)
            sys.exit(2)

        if row.get("qa_kind"):
            row["qa_kind"] = _normalize_qa_kind(row["qa_kind"])

        # Reject agent executor for browser QA kinds (only check when
        # qa_kind is supplied; the DB-aware pass below derives missing
        # values and re-runs this check).
        if row.get("qa_kind") and row["executor_type"] == "agent" and row["qa_kind"] in VALID_BROWSER_QA_KINDS:
            print(
                f"Error: row {idx}: executor_type 'agent' is not allowed for qa_kind '{row['qa_kind']}' -- use browser_substrate",
                file=sys.stderr,
            )
            sys.exit(2)

    # All rows validated — insert in one transaction
    conn = connect(path=db_path)
    inserted_ids: List[int] = []
    try:
        # Derive missing qa_kind from the requirement, and reject any
        # mismatch between caller-supplied qa_kind and the requirement.
        for idx, row in enumerate(payload):
            req_kind = query_scalar(
                conn,
                "SELECT qa_kind FROM qa_requirements WHERE id = %s",
                (row["requirement_id"],),
            )
            if not req_kind:
                print(
                    f"Error: row {idx}: requirement_id "
                    f"{row['requirement_id']} not found in qa_requirements",
                    file=sys.stderr,
                )
                sys.exit(2)
            normalized_req_kind = _normalize_qa_kind(str(req_kind))
            if not row.get("qa_kind"):
                row["qa_kind"] = normalized_req_kind
            else:
                row["qa_kind"] = _normalize_qa_kind(row["qa_kind"])
                if row["qa_kind"] != normalized_req_kind:
                    print(
                        f"Error: row {idx}: qa_kind '{row['qa_kind']}' "
                        f"does not match the requirement's stored kind "
                        f"'{normalized_req_kind}'. Omit qa_kind to use "
                        "the requirement's kind, or fix the value.",
                        file=sys.stderr,
                    )
                    sys.exit(2)
            # Re-run the agent-vs-browser-kind guard now that qa_kind is
            # always populated.
            if row["executor_type"] == "agent" and row["qa_kind"] in VALID_BROWSER_QA_KINDS:
                print(
                    f"Error: row {idx}: executor_type 'agent' is not "
                    f"allowed for qa_kind '{row['qa_kind']}' -- use "
                    "browser_substrate",
                    file=sys.stderr,
                )
                sys.exit(2)

        # Pre-validate screenshot evidence and epic review constraints using DB lookups
        for idx, row in enumerate(payload):
            if row["executor_type"] == "agent" and row["qa_kind"] == "ac_verification":
                req_policy = query_scalar(
                    conn,
                    "SELECT success_policy FROM qa_requirements WHERE id = %s",
                    (row["requirement_id"],),
                )
                if req_policy and "requires_screenshot_evidence" in str(req_policy):
                    print(
                        f"Error: row {idx}: executor_type 'agent' not allowed for ac_verification "
                        "with [requires_screenshot_evidence]",
                        file=sys.stderr,
                    )
                    sys.exit(2)

            if row["qa_kind"] == "implementation_review":
                target_row = query_one(
                    conn,
                    "SELECT COALESCE(CAST(item_id AS TEXT), '') AS item_id, COALESCE(CAST(epic_id AS TEXT), '') AS epic_id, "
                    "COALESCE(CAST(task_num AS TEXT), '') AS task_num FROM qa_requirements WHERE id = %s",
                    (row["requirement_id"],),
                )
                if target_row:
                    t_item = str(target_row["item_id"])
                    t_epic = str(target_row["epic_id"])
                    t_task = str(target_row["task_num"])
                    if not t_item and t_epic and t_task:
                        if os.environ.get("YOKE_INTERNAL_EPIC_REVIEW_WRITE") != "1":
                            print(
                                f"Error: row {idx}: epic-task qa_kind 'implementation_review' runs "
                                "must use db_router epic review-insert",
                                file=sys.stderr,
                            )
                            sys.exit(2)

        now_iso = iso8601_now()

        for row in payload:
            verdict = row.get("verdict")
            completed_at_value = None if verdict is None else now_iso

            sql = """INSERT INTO qa_runs
                      (qa_requirement_id, executor_type, qa_kind, verdict,
                       score, confidence, raw_result, duration_ms,
                       started_at, completed_at, created_at)
                      VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id"""
            cur = conn.execute(sql, (
                row["requirement_id"],
                row["executor_type"],
                row["qa_kind"],
                verdict,
                row.get("score"),
                row.get("confidence"),
                row.get("raw_result"),
                row.get("duration_ms"),
                now_iso, completed_at_value, now_iso,
            ))
            inserted_id = int(cur.fetchone()[0])
            inserted_ids.append(inserted_id)

            # optional one-step artifact creation
            artifact_path = row.get("artifact_path")
            if artifact_path is not None:
                _ext = os.path.splitext(artifact_path)[1].lower()
                _content_type = {
                    ".png": "image/png",
                    ".jpg": "image/jpeg",
                    ".jpeg": "image/jpeg",
                    ".webp": "image/webp",
                    ".gif": "image/gif",
                }.get(_ext, "application/octet-stream")
                # Explicit local handle, no canonicalizing DB reads: the
                # batch shares one transaction, so the single-run path's
                # rollback-on-lookup-failure shape would discard earlier
                # batch inserts.
                _handle = serialize_handle(local_handle(artifact_path))
                conn.execute(
                    """INSERT INTO qa_artifacts (qa_run_id, artifact_type, content_type, artifact_handle, metadata, created_at)
                       VALUES (%s, %s, %s, %s, %s, %s)""",
                    (inserted_id, "screenshot", _content_type, _handle, None, iso8601_now()),
                )

        # QA run writes are real item activity (R1 semantics).
        from yoke_core.domain.item_activity import touch_for_qa_requirement
        for row in payload:
            touch_for_qa_requirement(conn, row["requirement_id"])

        conn.commit()

        # Emit per-row events after commit
        for i, row in enumerate(payload):
            verdict = row.get("verdict")
            emit_qa_run_event(
                conn,
                db_path=db_path,
                event_name="QARunCompleted" if verdict is not None else "QARunStarted",
                run_id=inserted_ids[i],
                requirement_id=row["requirement_id"],
                qa_kind=row["qa_kind"],
                verdict=verdict,
            )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(json.dumps(inserted_ids))
    return inserted_ids
