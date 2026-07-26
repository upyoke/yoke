"""Auto-create basic QA requirements for workflow-selected items."""

from __future__ import annotations

import re
from typing import Optional

from yoke_core.domain.db_helpers import connect, iso8601_now
from yoke_core.domain.qa_events import emit_qa_requirement_event

PYTEST_TARGET = "python3 -m yoke_core.tools.watch_pytest -- runtime/api/"


def _should_create(row: dict, *, qa_policy: str) -> bool:
    del row
    return qa_policy == "project_transition_defaults"


def _ac_list(spec: str) -> str:
    acs = []
    for line in spec.splitlines():
        match = re.match(r"^- \[ \] (AC-\d+:\s*.*)$", line.strip())
        if match:
            acs.append(match.group(1).strip())
    return "; ".join(acs) if acs else "none listed"


def _existing_requirement(conn, item_id: int) -> Optional[int]:
    row = conn.execute(
        """SELECT id FROM qa_requirements
           WHERE item_id=%s AND qa_kind='ac_verification'
           AND qa_phase='verification' AND waived_at IS NULL
           ORDER BY id LIMIT 1""",
        (item_id,),
    ).fetchone()
    return int(row["id"]) if row else None


def auto_create_for_item(
    item_id: int,
    *,
    dry_run: bool = False,
    db_path: Optional[str] = None,
) -> Optional[int]:
    """Create one blocking AC verification requirement when appropriate."""
    conn = connect(path=db_path)
    try:
        existing = _existing_requirement(conn, item_id)
        if existing is not None:
            return existing
        row = conn.execute("SELECT * FROM items WHERE id=%s", (item_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        from yoke_core.domain.workflow_runtime import (
            load_item_workflow_runtime,
        )

        workflow = load_item_workflow_runtime(conn, item_id)
        if not _should_create(
            item,
            qa_policy=str(workflow.policies["qa"]),
        ):
            return None
        if dry_run:
            return None
        policy = f"pytest target: {PYTEST_TARGET}; AC list: {_ac_list(item.get('spec') or '')}"
        cur = conn.execute(
            """INSERT INTO qa_requirements
               (item_id, qa_kind, qa_phase, blocking_mode,
                requirement_source, success_policy, created_at)
               VALUES (%s, 'ac_verification', 'verification', 'blocking',
                       'ac_derived', %s, %s) RETURNING id""",
            (item_id, policy, iso8601_now()),
        )
        req_id = int(cur.fetchone()[0])
        # QA requirement writes are real item activity (R1 semantics).
        from yoke_core.domain.item_activity import touch_item_activity
        touch_item_activity(conn, item_id=item_id)
        conn.commit()
        emit_qa_requirement_event(
            conn,
            db_path=db_path,
            event_name="QARequirementCreated",
            requirement_id=req_id,
            qa_kind="ac_verification",
            qa_phase="verification",
            target_row={"item_id": item_id, "epic_id": None, "task_num": None,
                        "deployment_run_id": None},
            extra_detail={"source": "auto_ac_verification"},
        )
        return req_id
    finally:
        conn.close()


__all__ = ["PYTEST_TARGET", "auto_create_for_item"]
