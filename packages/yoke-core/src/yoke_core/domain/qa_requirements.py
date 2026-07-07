"""QA requirement add/add-batch + re-export shim.

Owns ``cmd_requirement_add`` and ``cmd_requirement_add_batch``; re-exports
the read/mutate ops, browser scenario surface, vocabulary constants, and
shared event helper for the supported public requirement surface.

Sibling modules: ``qa_constants`` (vocab + helpers), ``qa_requirement_ops``
(list/get/waive/update), ``qa_browser_scenarios`` (settle floor + scenarios),
``qa_events`` (lifecycle emission).
"""

from __future__ import annotations

import json
import sys
from typing import List, Optional

from yoke_core.domain.db_helpers import connect, iso8601_now
from yoke_core.domain.qa_browser_scenarios import (
    DEFAULT_SETTLE_MS,
    _inject_settle_delay,
    build_browser_requirements_from_metadata,
    build_browser_scenario_policy,
    min_delay_before_first_screenshot,
    read_browser_qa_metadata,
)
from yoke_core.domain.qa_constants import (
    VALID_BLOCKING_MODES,
    VALID_BROWSER_QA_KINDS,
    VALID_QA_PHASES,
    VALID_REQUIREMENT_SOURCES,
    VALID_VERDICTS,
    _REQ_SELECT,
    _coalesce,
    _normalize_qa_kind,
    _normalize_qa_phase,
    _pipe_row,
)
from yoke_core.domain.qa_events import emit_qa_requirement_event
from yoke_core.domain.qa_requirement_policy_validation import (
    validate_requirement_source,
    validate_success_policy,
)
from yoke_core.domain.qa_requirement_ops import (
    UPDATABLE_REQUIREMENT_FIELDS,
    cmd_requirement_get,
    cmd_requirement_list,
    cmd_requirement_update,
    cmd_requirement_waive,
)

__all__ = (
    # Vocabulary constants and helpers (sourced from qa_constants)
    "VALID_QA_PHASES",
    "VALID_BLOCKING_MODES",
    "VALID_REQUIREMENT_SOURCES",
    "VALID_VERDICTS",
    "VALID_BROWSER_QA_KINDS",
    "_REQ_SELECT",
    "_coalesce",
    "_normalize_qa_phase",
    "_normalize_qa_kind",
    "_pipe_row",
    # Browser scenario surface (sourced from qa_browser_scenarios)
    "DEFAULT_SETTLE_MS",
    "min_delay_before_first_screenshot",
    "_inject_settle_delay",
    "build_browser_scenario_policy",
    "read_browser_qa_metadata",
    "build_browser_requirements_from_metadata",
    # Read/mutate ops (sourced from qa_requirement_ops)
    "UPDATABLE_REQUIREMENT_FIELDS",
    "cmd_requirement_list",
    "cmd_requirement_get",
    "cmd_requirement_waive",
    "cmd_requirement_update",
    # Add path (defined here)
    "cmd_requirement_add",
    "cmd_requirement_add_batch",
)


# ---------------------------------------------------------------------------
# requirement-add
# ---------------------------------------------------------------------------

def cmd_requirement_add(
    *,
    db_path: Optional[str] = None,
    item_id: Optional[int] = None,
    epic_id: Optional[int] = None,
    task_num: Optional[int] = None,
    deployment_run_id: Optional[str] = None,
    qa_kind: str,
    qa_phase: str,
    target_env: Optional[str] = None,
    blocking_mode: str = "blocking",
    requirement_source: str = "explicit",
    success_policy: Optional[str] = None,
    capability_requirements: Optional[str] = None,
    suite_id: Optional[str] = None,
) -> int:
    """Insert a qa_requirement row. Returns the new ID."""
    # Validate required fields
    if not qa_kind:
        print("Error: --qa-kind is required", file=sys.stderr)
        sys.exit(2)
    if not qa_phase:
        print("Error: --qa-phase is required", file=sys.stderr)
        sys.exit(2)
    qa_phase = _normalize_qa_phase(qa_phase)
    qa_kind = _normalize_qa_kind(qa_kind)

    # Validate exactly one attachment target
    targets = 0
    if item_id is not None:
        targets += 1
    if epic_id is not None and task_num is not None:
        targets += 1
    if deployment_run_id is not None:
        targets += 1
    if targets == 0:
        print("Error: must specify one of --item-id, (--epic-id + --task-num), or --deployment-run-id", file=sys.stderr)
        sys.exit(2)
    if targets > 1:
        print("Error: must specify exactly one of --item-id, (--epic-id + --task-num), or --deployment-run-id", file=sys.stderr)
        sys.exit(2)
    if epic_id is not None and task_num is None:
        print("Error: --epic-id requires --task-num", file=sys.stderr)
        sys.exit(2)

    _exit_policy_errors(validate_requirement_source(requirement_source))
    _exit_policy_errors(validate_success_policy(qa_kind, success_policy))

    conn = connect(path=db_path)
    try:
        cur = conn.execute(
            """INSERT INTO qa_requirements
               (item_id, epic_id, task_num, deployment_run_id,
                qa_kind, qa_phase, target_env, blocking_mode,
                requirement_source, success_policy,
                capability_requirements, suite_id, created_at)
               VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
            (
                item_id,
                epic_id if epic_id is not None else None,
                task_num if task_num is not None else None,
                deployment_run_id,
                qa_kind, qa_phase, target_env, blocking_mode,
                requirement_source, success_policy,
                capability_requirements, suite_id, iso8601_now(),
            ),
        )
        inserted_id = int(cur.fetchone()[0])
        # QA requirement writes are real item activity.
        _qa_target = item_id if item_id is not None else epic_id
        if _qa_target is not None:
            from yoke_core.domain.item_activity import touch_item_activity
            touch_item_activity(conn, item_id=_qa_target)
        conn.commit()
        emit_qa_requirement_event(
            conn,
            db_path=db_path,
            event_name="QARequirementCreated",
            requirement_id=inserted_id,
            qa_kind=qa_kind,
            qa_phase=qa_phase,
            target_row={"item_id": item_id, "epic_id": epic_id, "task_num": task_num,
                        "deployment_run_id": deployment_run_id},
        )
    finally:
        conn.close()

    print(inserted_id)
    return inserted_id


# ---------------------------------------------------------------------------
# requirement-add-batch
# ---------------------------------------------------------------------------

def cmd_requirement_add_batch(
    *,
    db_path: Optional[str] = None,
    json_file: str,
) -> List[int]:
    """Insert multiple qa_requirement rows in one transaction. Returns list of new IDs.

    The JSON file must contain an array of objects with the same fields as
    requirement-add: item_id, epic_id, task_num, deployment_run_id, qa_kind,
    qa_phase, target_env, blocking_mode, requirement_source, success_policy,
    capability_requirements, suite_id.

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

    # Pre-validate every row before opening the transaction
    for idx, row in enumerate(payload):
        if not isinstance(row, dict):
            print(f"Error: row {idx} is not an object", file=sys.stderr)
            sys.exit(2)

        qa_kind = row.get("qa_kind")
        qa_phase = row.get("qa_phase")
        if not qa_kind:
            print(f"Error: row {idx} missing required field 'qa_kind'", file=sys.stderr)
            sys.exit(2)
        if not qa_phase:
            print(f"Error: row {idx} missing required field 'qa_phase'", file=sys.stderr)
            sys.exit(2)

        # Validate exactly one attachment target
        targets = 0
        if row.get("item_id") is not None:
            targets += 1
        if row.get("epic_id") is not None and row.get("task_num") is not None:
            targets += 1
        if row.get("deployment_run_id") is not None:
            targets += 1
        if targets == 0:
            print(f"Error: row {idx} must specify one of item_id, (epic_id + task_num), or deployment_run_id", file=sys.stderr)
            sys.exit(2)
        if targets > 1:
            print(f"Error: row {idx} must specify exactly one attachment target", file=sys.stderr)
            sys.exit(2)

        # Normalize in-place for the insert phase
        row["qa_phase"] = _normalize_qa_phase(qa_phase)
        row["qa_kind"] = _normalize_qa_kind(qa_kind)

        _exit_policy_errors(
            validate_requirement_source(
                row.get("requirement_source", "explicit"),
                label=f"row {idx}",
            )
        )
        _exit_policy_errors(
            validate_success_policy(
                row["qa_kind"],
                row.get("success_policy"),
                label=f"row {idx}",
            )
        )

    # All rows validated — insert in one transaction
    conn = connect(path=db_path)
    inserted_ids: List[int] = []
    try:
        for row in payload:
            cur = conn.execute(
                """INSERT INTO qa_requirements
                   (item_id, epic_id, task_num, deployment_run_id,
                    qa_kind, qa_phase, target_env, blocking_mode,
                    requirement_source, success_policy,
                    capability_requirements, suite_id, created_at)
                   VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s) RETURNING id""",
                (
                    row.get("item_id"),
                    row.get("epic_id"),
                    row.get("task_num"),
                    row.get("deployment_run_id"),
                    row["qa_kind"],
                    row["qa_phase"],
                    row.get("target_env"),
                    row.get("blocking_mode", "blocking"),
                    row.get("requirement_source", "explicit"),
                    row.get("success_policy"),
                    row.get("capability_requirements"),
                    row.get("suite_id"),
                    iso8601_now(),
                ),
            )
            inserted_ids.append(int(cur.fetchone()[0]))
        # QA requirement writes are real item activity.
        from yoke_core.domain.item_activity import touch_item_activity
        for row in payload:
            _qa_target = (
                row.get("item_id") if row.get("item_id") is not None
                else row.get("epic_id")
            )
            if _qa_target is not None:
                touch_item_activity(conn, item_id=_qa_target)
        conn.commit()

        # Emit per-row events after commit
        for i, row in enumerate(payload):
            emit_qa_requirement_event(
                conn,
                db_path=db_path,
                event_name="QARequirementCreated",
                requirement_id=inserted_ids[i],
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


def _exit_policy_errors(errors: list[str]) -> None:
    if not errors:
        return
    for error in errors:
        print(f"Error: {error}", file=sys.stderr)
    sys.exit(2)
