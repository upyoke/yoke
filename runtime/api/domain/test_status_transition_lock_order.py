"""Two-connection status and workflow-binding lock-order proofs."""

from __future__ import annotations

import threading
from typing import Any

from runtime.api.domain.test_status_transition_preflight import (
    TARGET_STATUS,
    _isolate_status_effects,
    _publish_approval_workflow,
)
from runtime.api.fixtures.backlog import insert_item, insert_qa_requirement
from runtime.api.fixtures.pg_testdb import connect_test_database
from yoke_core.domain import (
    backlog,
    backlog_status_write_precondition,
    backlog_update_op,
)
from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)
from yoke_core.domain.workflow_item_versioning import (
    migrate_item_workflow_pin,
)


def test_gate_dependency_writer_waits_for_status_transaction(
    test_db,
    monkeypatch,
) -> None:
    """No gate child can land between evaluation and status commit."""
    _isolate_status_effects(monkeypatch)
    _publish_approval_workflow(
        test_db,
        label="Gate dependency serialization",
        enabled=False,
    )
    item_id = 973
    insert_item(test_db, id=item_id, workflow_id="issue", status="idea")
    database_name = str(test_db.info.dbname)
    writer_conn = connect_test_database(database_name)
    gate_entered = threading.Event()
    continue_gate = threading.Event()
    writer_started = threading.Event()
    writer_done = threading.Event()
    outcomes: dict[str, Any] = {}

    def pause_gate(**_kwargs):
        gate_entered.set()
        assert continue_gate.wait(timeout=10)
        return None

    monkeypatch.setattr(
        backlog_update_op,
        "_run_authoritative_status_gate",
        pause_gate,
    )

    def transition() -> None:
        outcomes["transition"] = backlog.execute_update(
            item_id=item_id,
            field="status",
            value=TARGET_STATUS,
            force=True,
            no_github=True,
            rebuild_board=False,
        )

    def add_gate_dependency() -> None:
        writer_started.set()
        try:
            lock_item_workflow_bindings(writer_conn, (item_id,))
            insert_qa_requirement(
                writer_conn,
                item_id=item_id,
                workflow_transition_id=TARGET_STATUS,
            )
            outcomes["writer"] = "inserted"
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["writer"] = exc
        finally:
            writer_done.set()

    status_writer = threading.Thread(
        target=transition,
        name="status-gate-parent-lock",
    )
    child_writer = threading.Thread(
        target=add_gate_dependency,
        name="status-gate-child-writer",
    )
    try:
        status_writer.start()
        assert gate_entered.wait(timeout=10)
        child_writer.start()
        assert writer_started.wait(timeout=10)
        assert not writer_done.wait(timeout=0.2)
        continue_gate.set()
        status_writer.join(timeout=10)
        child_writer.join(timeout=10)
    finally:
        continue_gate.set()
        writer_conn.close()

    assert not status_writer.is_alive()
    assert not child_writer.is_alive()
    assert outcomes["transition"]["success"] is True
    assert outcomes["writer"] == "inserted"
    status = test_db.execute(
        "SELECT status FROM items WHERE id=%s",
        (item_id,),
    ).fetchone()[0]
    assert str(status) == TARGET_STATUS


def test_transition_first_forces_migration_to_observe_reached_stage(
    test_db,
    monkeypatch,
) -> None:
    _isolate_status_effects(monkeypatch)
    source = _publish_approval_workflow(
        test_db,
        label="Transition-first workflow",
        enabled=False,
    )
    item_id = 968
    insert_item(test_db, id=item_id, workflow_id="issue", status="idea")
    target = _publish_approval_workflow(
        test_db,
        label="Migration approval target",
        enabled=True,
    )
    database = str(test_db.info.dbname)
    migration_conn = connect_test_database(database)
    status_locked = threading.Event()
    continue_status = threading.Event()
    migration_started = threading.Event()
    migration_done = threading.Event()
    outcomes: dict[str, Any] = {}
    original_update = backlog_status_write_precondition._update_item_multi

    def pause_with_status_lock(conn, bound_item_id, writes, **kwargs):
        status_locked.set()
        assert continue_status.wait(timeout=10)
        return original_update(conn, bound_item_id, writes, **kwargs)

    monkeypatch.setattr(
        backlog_status_write_precondition,
        "_update_item_multi",
        pause_with_status_lock,
    )

    def transition() -> None:
        outcomes["transition"] = backlog.execute_update(
            item_id=item_id,
            field="status",
            value=TARGET_STATUS,
            expected_status="idea",
            force=True,
            no_github=True,
            rebuild_board=False,
        )

    def migrate() -> None:
        migration_started.set()
        try:
            outcomes["migration"] = migrate_item_workflow_pin(
                migration_conn,
                item_id=item_id,
                target_version=int(target["version"]),
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["migration"] = exc
        finally:
            migration_done.set()

    transition_thread = threading.Thread(
        target=transition,
        name="status-writer-first",
    )
    migration_thread = threading.Thread(
        target=migrate,
        name="workflow-migrator-second",
    )
    try:
        transition_thread.start()
        assert status_locked.wait(timeout=10)
        migration_thread.start()
        assert migration_started.wait(timeout=10)
        assert not migration_done.wait(timeout=0.2)
    finally:
        continue_status.set()
        transition_thread.join(timeout=10)
        migration_thread.join(timeout=10)
        migration_conn.close()

    assert not transition_thread.is_alive()
    assert not migration_thread.is_alive()
    assert outcomes["transition"]["success"] is True
    assert isinstance(outcomes["migration"], WorkflowRegistryError)
    assert "unsatisfied approval semantics" in str(outcomes["migration"])
    row = test_db.execute(
        "SELECT workflow_version_id, status FROM items WHERE id=%s",
        (item_id,),
    ).fetchone()
    assert (int(row[0]), str(row[1])) == (
        int(source["version_id"]),
        TARGET_STATUS,
    )
