"""QA requirement add/add-batch + re-export shim.

Owns ``cmd_requirement_add`` and ``cmd_requirement_add_batch``; re-exports
the read/mutate ops, vocabulary constants, and shared event helper for the
supported public requirement surface.

Sibling modules: ``qa_constants`` (vocab + helpers), ``qa_requirement_ops``
(list/get/waive/update), ``qa_events`` (lifecycle emission).
"""

from __future__ import annotations

import sys
from typing import Optional

from yoke_core.domain.db_helpers import connect, iso8601_now
from yoke_core.domain.qa_constants import (
    BROWSER_METHOD_IDS,
    VALID_BLOCKING_MODES,
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
from yoke_core.domain.qa_cli_transition_binding import require_cli_workflow_transition
from yoke_core.domain.qa_cli_requirement_insert import INSERT_SQL, insert_params
from yoke_core.domain.qa_requirement_batch import cmd_requirement_add_batch

__all__ = (
    # Vocabulary constants and helpers (sourced from qa_constants)
    "VALID_QA_PHASES",
    "VALID_BLOCKING_MODES",
    "VALID_REQUIREMENT_SOURCES",
    "VALID_VERDICTS",
    "BROWSER_METHOD_IDS",
    "_REQ_SELECT",
    "_coalesce",
    "_normalize_qa_phase",
    "_normalize_qa_kind",
    "_pipe_row",
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
    workflow_transition_id: Optional[str] = None,
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
        print(
            "Error: must specify one of --item-id, (--epic-id + --task-num), or --deployment-run-id",
            file=sys.stderr,
        )
        sys.exit(2)
    if targets > 1:
        print(
            "Error: must specify exactly one of --item-id, (--epic-id + --task-num), or --deployment-run-id",
            file=sys.stderr,
        )
        sys.exit(2)
    if epic_id is not None and task_num is None:
        print("Error: --epic-id requires --task-num", file=sys.stderr)
        sys.exit(2)

    _exit_policy_errors(validate_requirement_source(requirement_source))
    _exit_policy_errors(validate_success_policy(qa_kind, success_policy))

    conn = connect(path=db_path)
    try:
        from yoke_core.domain.workflow_item_binding_lock import (
            lock_item_workflow_bindings,
        )

        binding_item_id = item_id if item_id is not None else epic_id
        if binding_item_id is not None:
            lock_item_workflow_bindings(conn, (int(binding_item_id),))
            workflow_transition_id = require_cli_workflow_transition(
                conn,
                item_id=int(binding_item_id),
                transition_id=workflow_transition_id,
            )
        row = {
            "qa_kind": qa_kind,
            "qa_phase": qa_phase,
            "target_env": target_env,
            "blocking_mode": blocking_mode,
            "requirement_source": requirement_source,
            "success_policy": success_policy,
            "capability_requirements": capability_requirements,
            "suite_id": suite_id,
            "workflow_transition_id": workflow_transition_id,
        }
        cur = conn.execute(
            INSERT_SQL,
            insert_params(
                item_id=item_id,
                epic_id=epic_id,
                task_num=task_num,
                deployment_run_id=deployment_run_id,
                row=row,
                created_at=iso8601_now(),
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
            target_row={
                "item_id": item_id,
                "epic_id": epic_id,
                "task_num": task_num,
                "deployment_run_id": deployment_run_id,
            },
        )
    finally:
        conn.close()

    print(inserted_id)
    return inserted_id


def _exit_policy_errors(errors: list[str]) -> None:
    if not errors:
        return
    for error in errors:
        print(f"Error: {error}", file=sys.stderr)
    sys.exit(2)
