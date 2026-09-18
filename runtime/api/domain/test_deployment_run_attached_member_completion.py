"""Completed items preserve deployment runs they joined while eligible."""

from __future__ import annotations

import json
from typing import Any

import pytest

from runtime.api.domain.test_deployment_run_composition_freeze import (
    _environment,
    _flow,
    _known_carried,
    _run,
)
from runtime.api.fixtures.backlog_inserts import insert_item
from yoke_core.domain import deployment_run_composition_freeze as composition
from yoke_core.domain.deployment_runs_crud_mutate import cmd_add_item, cmd_update
from yoke_core.domain.deployment_runs_validation import (
    cmd_check_batch_compatibility,
    cmd_validate_composition,
)
from yoke_core.domain.workflow_item_binding_validation import (
    WorkflowItemBindingError,
)


def _member(conn: Any, item_id: int, flow_id: str) -> None:
    insert_item(
        conn,
        id=item_id,
        project_sequence=item_id - 9000,
        workflow_id="blitz",
        status="implementing",
        deployment_flow=flow_id,
    )


def test_attached_member_completion_preserves_intent_validation_and_execution(
    test_db: Any,
    monkeypatch,
) -> None:
    _environment(test_db)
    _flow(test_db, "attached-completion", advanced=True)
    _member(test_db, 9451, "attached-completion")
    _run(test_db, "run-attached-completion", "attached-completion", lineage="a" * 40)
    cmd_add_item("run-attached-completion", 9451, delivery_intent="progress")

    test_db.execute("UPDATE items SET status='done' WHERE id=9451")
    test_db.commit()
    assert cmd_validate_composition("run-attached-completion") == (True, "OK")
    monkeypatch.setattr(
        composition,
        "record_carried_work",
        lambda _conn, _run_id: _known_carried(9451),
    )

    assert cmd_update("run-attached-completion", "status", "executing") is None
    run = test_db.execute(
        "SELECT status,composition_frozen_at FROM deployment_runs "
        "WHERE id='run-attached-completion'"
    ).fetchone()
    member = test_db.execute(
        "SELECT delivery_intent,requirement_snapshot FROM deployment_run_items "
        "WHERE run_id='run-attached-completion' AND item_id=9451"
    ).fetchone()
    assert run["status"] == "executing"
    assert run["composition_frozen_at"]
    assert member["delivery_intent"] == "progress"
    assert json.loads(member["requirement_snapshot"])["requirements"] == []


def test_terminal_item_cannot_be_newly_admitted(test_db: Any) -> None:
    _environment(test_db)
    _flow(test_db, "terminal-admission", advanced=True)
    _member(test_db, 9452, "terminal-admission")
    test_db.execute("UPDATE items SET status='done' WHERE id=9452")
    test_db.commit()
    _run(test_db, "run-terminal-admission", "terminal-admission", lineage="b" * 40)

    compatible, message = cmd_check_batch_compatibility(
        "yoke", "terminal-admission", [9452]
    )
    assert compatible is False
    assert "status=done" in message
    with pytest.raises(WorkflowItemBindingError, match="terminal.*done"):
        cmd_add_item("run-terminal-admission", 9452)


def test_completed_member_survives_a_later_selected_flow_change(test_db: Any) -> None:
    _environment(test_db)
    _flow(test_db, "completion-alignment", advanced=True)
    _member(test_db, 9455, "completion-alignment")
    _run(test_db, "run-completion-alignment", "completion-alignment", lineage="d" * 40)
    cmd_add_item("run-completion-alignment", 9455)
    test_db.execute(
        "UPDATE items SET status='done',deployment_flow='another-flow' WHERE id=9455"
    )
    test_db.commit()

    refusal = cmd_update("run-completion-alignment", "status", "executing")

    assert refusal is None
    run = test_db.execute(
        "SELECT status,composition_frozen_at FROM deployment_runs "
        "WHERE id='run-completion-alignment'"
    ).fetchone()
    assert run["status"] == "executing"
    assert run["composition_frozen_at"]


@pytest.mark.parametrize("terminal_status", ["cancelled", "stopped"])
def test_engine_terminal_member_cannot_start_a_run(
    test_db: Any,
    terminal_status: str,
) -> None:
    _environment(test_db)
    flow_id = f"attached-{terminal_status}"
    run_id = f"run-attached-{terminal_status}"
    item_id = 9453 if terminal_status == "cancelled" else 9454
    _flow(test_db, flow_id, advanced=True)
    _member(test_db, item_id, flow_id)
    _run(test_db, run_id, flow_id, lineage="c" * 40)
    cmd_add_item(run_id, item_id)
    test_db.execute(
        "UPDATE items SET status=%s WHERE id=%s", (terminal_status, item_id)
    )
    test_db.commit()

    refusal = cmd_update(run_id, "status", "executing")

    assert refusal is not None
    assert f"terminal at workflow stage '{terminal_status}'" in refusal
    run = test_db.execute(
        "SELECT status,composition_frozen_at FROM deployment_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    assert tuple(run) == ("created", None)
