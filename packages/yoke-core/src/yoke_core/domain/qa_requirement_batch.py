"""Atomic batch insertion for QA requirements."""

from __future__ import annotations

import json
import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import connect, iso8601_now
from yoke_core.domain.qa_cli_requirement_insert import INSERT_SQL, insert_params
from yoke_core.domain.qa_cli_transition_binding import require_cli_workflow_transition
from yoke_core.domain.qa_constants import _normalize_qa_kind, _normalize_qa_phase
from yoke_core.domain.qa_events import emit_qa_requirement_event
from yoke_core.domain.qa_requirement_policy_validation import (
    validate_requirement_source,
    validate_success_policy,
)


def cmd_requirement_add_batch(
    *,
    db_path: Optional[str] = None,
    json_file: str,
) -> List[int]:
    """Insert validated requirement rows in one transaction."""
    try:
        with open(json_file, "r") as f:
            payload = json.load(f)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"Error: cannot read/parse --json-file: {exc}", file=sys.stderr)
        sys.exit(2)

    if not isinstance(payload, list):
        print("Error: --json-file must contain a JSON array", file=sys.stderr)
        sys.exit(2)
    if not payload:
        print("Error: --json-file array is empty", file=sys.stderr)
        sys.exit(2)

    for idx, row in enumerate(payload):
        _validate_row(row, idx)

    conn = connect(path=db_path)
    inserted_ids: List[int] = []
    try:
        from yoke_core.domain.workflow_item_binding_lock import (
            lock_item_workflow_bindings,
        )

        lock_item_workflow_bindings(
            conn,
            (
                int(
                    row["item_id"] if row.get("item_id") is not None else row["epic_id"]
                )
                for row in payload
                if row.get("item_id") is not None or row.get("epic_id") is not None
            ),
        )
        for row in payload:
            binding_item_id = (
                row.get("item_id")
                if row.get("item_id") is not None
                else row.get("epic_id")
            )
            if binding_item_id is not None:
                row["workflow_transition_id"] = require_cli_workflow_transition(
                    conn,
                    item_id=int(binding_item_id),
                    transition_id=row.get("workflow_transition_id"),
                    label=f"row {len(inserted_ids)}",
                )
            cur = conn.execute(
                INSERT_SQL,
                insert_params(
                    item_id=row.get("item_id"),
                    epic_id=row.get("epic_id"),
                    task_num=row.get("task_num"),
                    deployment_run_id=row.get("deployment_run_id"),
                    row=row,
                    created_at=iso8601_now(),
                ),
            )
            inserted_ids.append(int(cur.fetchone()[0]))

        from yoke_core.domain.item_activity import touch_item_activity

        for row in payload:
            target = (
                row.get("item_id")
                if row.get("item_id") is not None
                else row.get("epic_id")
            )
            if target is not None:
                touch_item_activity(conn, item_id=target)
        conn.commit()

        for index, row in enumerate(payload):
            emit_qa_requirement_event(
                conn,
                db_path=db_path,
                event_name="QARequirementCreated",
                requirement_id=inserted_ids[index],
                qa_kind=row["qa_kind"],
                qa_phase=row["qa_phase"],
            )
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

    print(json.dumps(inserted_ids))
    return inserted_ids


def _validate_row(row, index: int) -> None:
    if not isinstance(row, dict):
        _exit(f"row {index} is not an object")
    qa_kind = row.get("qa_kind")
    qa_phase = row.get("qa_phase")
    if not qa_kind:
        _exit(f"row {index} missing required field 'qa_kind'")
    if not qa_phase:
        _exit(f"row {index} missing required field 'qa_phase'")

    targets = sum(
        (
            row.get("item_id") is not None,
            row.get("epic_id") is not None and row.get("task_num") is not None,
            row.get("deployment_run_id") is not None,
        )
    )
    if targets == 0:
        _exit(
            f"row {index} must specify one of item_id, "
            "(epic_id + task_num), or deployment_run_id"
        )
    if targets > 1:
        _exit(f"row {index} must specify exactly one attachment target")

    row["qa_phase"] = _normalize_qa_phase(qa_phase)
    row["qa_kind"] = _normalize_qa_kind(qa_kind)
    _exit_policy_errors(
        validate_requirement_source(
            row.get("requirement_source", "explicit"),
            label=f"row {index}",
        )
    )
    _exit_policy_errors(
        validate_success_policy(
            row["qa_kind"],
            row.get("success_policy"),
            label=f"row {index}",
        )
    )


def _exit(message: str) -> None:
    print(f"Error: {message}", file=sys.stderr)
    sys.exit(2)


def _exit_policy_errors(errors: list[str]) -> None:
    if not errors:
        return
    for error in errors:
        print(f"Error: {error}", file=sys.stderr)
    sys.exit(2)
