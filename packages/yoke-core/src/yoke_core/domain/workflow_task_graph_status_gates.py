"""Task-graph gates a pinned definition carries by its own structure.

A definition whose ``generated_children`` policy is ``epic_tasks`` executes
through a task graph the planning segment authors. Its implementation
binding — the bound skill that executes the graph — delimits three facts:

* existence: from that binding's entry stage on, the graph has tasks;
* completion: from that binding's handoff stage on, every task has itself
  reached the handoff stage;
* deferred work: the successful terminal stage refuses unfiled deferrals.

A definition with a ``shepherd`` binding also requires shepherd's terminal
plan verdict on the transition where its implementation binding starts work. None of these
is listed on a stage; each holds for a plain ``lifecycle.transition``.
"""

from __future__ import annotations

from yoke_contracts.skill_registry import IMPLEMENTATION_SKILL_IDS

from typing import Any, Mapping, Optional

from yoke_core.domain.db_helpers import query_rows
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.qa_gate_definitions import status_settles_blocking_qa
from yoke_core.domain.schema_common import _table_exists
from yoke_core.domain.workflow_behavior import generates_task_graph

_SHEPHERD_SKILL_ID = "shepherd"


def _p(conn: Any) -> str:
    from yoke_core.domain import db_backend

    return "%s" if db_backend.connection_is_postgres(conn) else "?"


def implementation_binding(workflow: Any) -> Optional[Mapping[str, Any]]:
    """The first binding whose skill executes implementation work."""
    for binding in workflow.definition["skill_bindings"]:
        if str(binding["skill_id"]) in IMPLEMENTATION_SKILL_IDS:
            return binding
    return None


def _reached(workflow: Any, target_status: str, stage_id: str) -> bool:
    return workflow.has_reached_stage(target_status, str(stage_id))


def _task_registry_present(conn: Any, item_id: int, target_status: str) -> bool:
    """Record a gate absence rather than crash on a universe with no tasks table."""
    if _table_exists(conn, "epic_tasks"):
        return True
    from yoke_core.domain.workflow_gate_absence import record_gate_absence

    record_gate_absence(
        gate_id="task_graph",
        item_id=int(item_id),
        target_status=target_status,
        reason="task_registry_absent",
        detail="this universe has no epic_tasks registry to read",
        conn=conn,
    )
    return False


def _task_rows(conn: Any, item_id: int) -> list:
    return query_rows(
        conn,
        f"SELECT task_num, status FROM epic_tasks WHERE epic_id = {_p(conn)} "
        "ORDER BY task_num",
        (int(item_id),),
    )


def evaluate_task_existence(
    *, conn: Any, item_id: int, target_status: str, workflow: Any, **_: Any
) -> Optional[dict]:
    """The task graph exists before the binding that executes it is entered."""
    binding = implementation_binding(workflow)
    if not generates_task_graph(workflow) or binding is None:
        return None
    if not _reached(workflow, target_status, binding["from_stage_id"]):
        return None
    if not _task_registry_present(conn, item_id, target_status):
        return None
    if _task_rows(conn, item_id):
        return None
    ref = render_item_ref(conn, int(item_id))
    return {
        "success": False,
        "error_code": "GATE_EPIC_TASKS",
        "error": (
            f"Cannot advance {ref} to {target_status!r} — no generated tasks "
            f"are recorded, and {binding['from_stage_id']!r} onward executes "
            "the task graph."
        ),
        "remediation_hint": f"Run `/yoke shepherd {ref}` to author the task graph.",
    }


def evaluate_task_completion(
    *, conn: Any, item_id: int, target_status: str, workflow: Any, **_: Any
) -> Optional[dict]:
    """The parent leaves task execution only after every task has."""
    binding = implementation_binding(workflow)
    if not generates_task_graph(workflow) or binding is None:
        return None
    handoff = str(binding["through_stage_id"])
    if not _reached(workflow, target_status, handoff):
        return None
    if not _task_registry_present(conn, item_id, target_status):
        return None
    rows = _task_rows(conn, item_id)
    unfinished = [
        f"task {row['task_num']} ({row['status']})"
        for row in rows
        if str(row["status"]) not in workflow.terminal_stage_ids
        and not workflow.has_reached_stage(str(row["status"]), handoff)
    ]
    if rows and not unfinished:
        return None
    ref = render_item_ref(conn, int(item_id))
    detail = ", ".join(unfinished) if unfinished else "no generated tasks exist"
    return {
        "success": False,
        "error_code": "GATE_EPIC_TASKS_INCOMPLETE",
        "error": (
            f"Cannot advance {ref} to {target_status!r} — every generated task "
            f"must reach {handoff!r} first: {detail}."
        ),
        "remediation_hint": (
            f"Finish the named tasks through `/yoke {binding['skill_id']} {ref}`."
        ),
    }


def evaluate_deferred_items(
    *, conn: Any, item_id: int, target_status: str, workflow: Any, **_: Any
) -> Optional[dict]:
    """A task-graph parent completes only with its deferrals filed."""
    from yoke_core.domain.deferred_item_tracking import (
        DEFERRED_ITEMS_HEADING,
        deferral_findings,
        describe_finding,
        item_deferral_text,
    )

    if not generates_task_graph(workflow):
        return None
    if target_status not in workflow.terminal_stage_ids:
        return None
    if not status_settles_blocking_qa(target_status):
        return None
    findings = deferral_findings(item_deferral_text(conn, int(item_id)))
    if not findings:
        return None
    ref = render_item_ref(conn, int(item_id))
    return {
        "success": False,
        "error_code": "GATE_DEFERRED_ITEMS_UNFILED",
        "error": (
            f"Cannot complete {ref} — it "
            + "; it ".join(describe_finding(finding) for finding in findings)
            + "."
        ),
        "remediation_hint": (
            "File each deferral with `/yoke idea` and record its item "
            f"reference under {DEFERRED_ITEMS_HEADING}."
        ),
    }


def evaluate_shepherd_verdict(
    *, conn: Any, item_id: int, target_status: str, workflow: Any, **_: Any
) -> Optional[dict]:
    """Implementation work starts only after shepherd signed off the plan."""
    from yoke_core.domain import shepherd_gate

    bindings = workflow.definition["skill_bindings"]
    if not any(str(b["skill_id"]) == _SHEPHERD_SKILL_ID for b in bindings):
        return None
    binding = implementation_binding(workflow)
    if binding is None:
        return None
    if target_status != workflow.next_stage_id(str(binding["from_stage_id"])):
        return None  # checked once, where implementation work begins
    if not _table_exists(conn, "shepherd_verdicts"):
        from yoke_core.domain.workflow_gate_absence import record_gate_absence

        record_gate_absence(
            gate_id="shepherd_verdict",
            item_id=int(item_id),
            target_status=target_status,
            reason="shepherd_verdict_registry_absent",
            detail="this universe has no shepherd_verdicts registry to read",
            conn=conn,
        )
        return None
    result = shepherd_gate.check_gate(int(item_id), conn=conn)
    if result.passed:
        return None
    return {
        "success": False,
        "error_code": "GATE_SHEPHERD_VERDICT",
        "error": f"Cannot advance to {target_status!r} — {result.reason}",
        "remediation_hint": (
            "Shepherd writes this verdict at its pinned handoff; run "
            f"`/yoke shepherd {render_item_ref(conn, int(item_id))}` while the "
            "item is still inside shepherd's segment."
        ),
    }


__all__ = [
    "evaluate_deferred_items",
    "evaluate_shepherd_verdict",
    "evaluate_task_completion",
    "evaluate_task_existence",
    "implementation_binding",
]
