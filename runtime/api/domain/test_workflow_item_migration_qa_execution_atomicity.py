"""Serialization proof for stale QA execution replacement."""

from __future__ import annotations

from copy import deepcopy
import threading
from typing import Any

import pytest

from runtime.api.domain.test_qa_plan_execution_authority import (
    _materialize_two_cases,
)
from runtime.api.domain.test_workflow_item_migration_compatibility import (
    ITEM_ID,
    _pin,
    _seed_path_claim,
)
from runtime.api.fixtures.pg_testdb import connect_test_database
from runtime.api.fixtures.backlog import insert_item
from yoke_core.domain import qa_plan_execution_state
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.qa_plan_attachments import (
    attach_plan_to_item,
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)
from yoke_core.domain.workflow_item_versioning import (
    migrate_item_workflow_pin,
)
from yoke_core.domain.workflow_registry import publish_workflow_version


def test_stale_execution_replacement_relocks_after_committing_cleanup(
    test_db,
    monkeypatch,
) -> None:
    _materialize_two_cases(test_db, item_id=ITEM_ID)
    definition = deepcopy(builtin_workflow_definition("issue")["definition"])
    definition["stages"][0]["label"] = "QA replacement migration target"
    target = publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=definition,
    )
    _seed_path_claim(test_db)
    stale = qa_plan_execution_state.begin_plan_execution(
        test_db,
        item_id=ITEM_ID,
        transition_id="implemented",
        actor_id="7",
        session_id="stale-session",
    )
    test_db.execute(
        "UPDATE qa_plan_executions SET heartbeat_at='2000-01-01T00:00:00Z' WHERE id=%s",
        (str(stale["id"]),),
    )
    test_db.commit()

    begin_conn = connect_test_database(str(test_db.info.dbname))
    migration_conn = connect_test_database(str(test_db.info.dbname))
    cleanup_committed = threading.Event()
    allow_relock = threading.Event()
    begin_done = threading.Event()
    outcomes: dict[str, Any] = {}
    original_cleanup = qa_plan_execution_state._release_stale_execution

    def pause_after_cleanup(conn: Any, execution: Any, *, now: str) -> None:
        original_cleanup(conn, execution, now=now)
        cleanup_committed.set()
        assert allow_relock.wait(timeout=10)

    monkeypatch.setattr(
        qa_plan_execution_state,
        "_release_stale_execution",
        pause_after_cleanup,
    )

    def replace_execution() -> None:
        try:
            outcomes["begin"] = qa_plan_execution_state.begin_plan_execution(
                begin_conn,
                item_id=ITEM_ID,
                transition_id="implemented",
                actor_id="8",
                session_id="replacement-session",
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["begin"] = exc
        finally:
            begin_done.set()

    replacement = threading.Thread(
        target=replace_execution,
        name="stale-qa-execution-replacement",
    )
    try:
        replacement.start()
        assert cleanup_committed.wait(timeout=10)
        lock_item_workflow_bindings(migration_conn, (ITEM_ID,))
        allow_relock.set()
        assert not begin_done.wait(timeout=0.2)
        outcomes["migration"] = migrate_item_workflow_pin(
            migration_conn,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )
        replacement.join(timeout=10)
        assert not replacement.is_alive()
    except BaseException:
        allow_relock.set()
        migration_conn.rollback()
        replacement.join(timeout=10)
        raise
    finally:
        begin_conn.close()
        migration_conn.close()

    assert not isinstance(outcomes["begin"], BaseException)
    assert outcomes["begin"]["state"] == "active"
    assert outcomes["migration"]["changed"] is True
    assert _pin(test_db) == (int(target["version_id"]), "idea")


@pytest.mark.parametrize("writer_kind", ("attach", "materialize"))
def test_migration_first_rejects_qa_binding_without_future_enforcement(
    test_db,
    writer_kind: str,
) -> None:
    item_id = 9890
    source_definition = deepcopy(builtin_workflow_definition("issue")["definition"])
    source_definition["stages"][0]["label"] = "QA binding source"
    source_definition["policies"]["path_claims"] = "optional"
    publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=source_definition,
    )
    insert_item(test_db, id=item_id, workflow_id="issue", status="idea")
    plan = create_plan(
        test_db,
        project="yoke",
        slug=f"qa-binding-{writer_kind}",
        name=f"QA binding {writer_kind}",
    )
    replace_plan_cases(
        test_db,
        plan_id=int(plan["id"]),
        cases=[
            {
                "case_key": "smoke",
                "position": 1,
                "method_id": "command",
                "instructions": "Run smoke.",
                "expected_outcome": "Smoke passes.",
                "method_config": {"command": "true"},
            }
        ],
    )
    if writer_kind == "materialize":
        set_project_default(
            test_db,
            plan_id=int(plan["id"]),
            workflow_id="issue",
            transition_id="refining-idea",
        )
    target_definition = deepcopy(source_definition)
    target_definition["stages"][0]["label"] = "QA binding target"
    for stage in target_definition["stages"]:
        stage["gates"] = [
            gate for gate in stage["gates"] if gate["id"] != "qa_verification"
        ]
    target = publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=target_definition,
    )
    db_name = str(test_db.info.dbname)
    migration_conn = connect_test_database(db_name)
    writer_conn = connect_test_database(db_name)
    writer_started = threading.Event()
    writer_done = threading.Event()
    outcomes: dict[str, Any] = {}

    def write_binding() -> None:
        writer_started.set()
        try:
            if writer_kind == "attach":
                attach_plan_to_item(
                    writer_conn,
                    plan_id=int(plan["id"]),
                    item_id=item_id,
                    transition_id="refining-idea",
                )
            else:
                materialize_for_item(
                    writer_conn,
                    item_id=item_id,
                    transition_id="refining-idea",
                )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["writer"] = exc
        finally:
            writer_done.set()

    writer = threading.Thread(target=write_binding, name=f"qa-{writer_kind}")
    try:
        lock_item_workflow_bindings(migration_conn, (item_id,))
        writer.start()
        assert writer_started.wait(timeout=10)
        assert not writer_done.wait(timeout=0.2)
        outcomes["migration"] = migrate_item_workflow_pin(
            migration_conn,
            item_id=item_id,
            target_version=int(target["version"]),
        )
        writer.join(timeout=10)
        assert not writer.is_alive()
    finally:
        migration_conn.close()
        writer_conn.close()

    assert outcomes["migration"]["changed"] is True
    assert isinstance(outcomes["writer"], QaPlanError)
    assert "no reachable qa_verification gate" in str(outcomes["writer"])
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_plan_item_attachments WHERE item_id=%s",
            (item_id,),
        ).fetchone()[0]
        == 0
    )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM qa_requirements WHERE item_id=%s",
            (item_id,),
        ).fetchone()[0]
        == 0
    )
