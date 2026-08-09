"""Current-pin validation after the shared item binding lock."""

from __future__ import annotations

from yoke_core.domain.workflow_definition_builders import (
    with_generated_epic_tasks,
)

from copy import deepcopy
import threading
from typing import Any

import pytest

from runtime.api.fixtures.backlog import (
    insert_deployment_run,
    insert_epic_task,
    insert_item,
)
from runtime.api.fixtures.pg_testdb import connect_test_database
from runtime.api.test_sessions import _register
from yoke_core.domain import deployment_runs_crud_mutate
from yoke_core.domain._path_claims_test_helpers import local_human
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.path_claims import InvalidWorkflowBinding
from yoke_core.domain.path_claims_exception import register_exception
from yoke_core.domain.sessions import SessionError, claim_work
from yoke_core.domain.sessions_lifecycle_reactivation import (
    auto_reacquire_session_ended_claims,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.work_claim_targets import make_epic_task_target
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)
from yoke_core.domain.workflow_item_versioning import migrate_item_workflow_pin
from yoke_core.domain.workflow_registry import publish_workflow_version


def _publish(
    test_db: Any,
    workflow_id: str,
    *,
    label: str,
    mutate: Any = None,
) -> dict[str, Any]:
    definition = deepcopy(builtin_workflow_definition(workflow_id)["definition"])
    definition["stages"][0]["label"] = label
    definition["policies"]["path_claims"] = "optional"
    if mutate is not None:
        mutate(definition)
    return publish_workflow_version(
        test_db,
        workflow_id=workflow_id,
        definition=definition,
    )


def _connections(test_db: Any) -> tuple[Any, Any]:
    name = str(test_db.info.dbname)
    return connect_test_database(name), connect_test_database(name)


def test_migration_first_rejects_an_epic_task_claim_under_item_only_policy(
    test_db: Any,
) -> None:
    _publish(test_db, "epic", label="Task-claim source")
    item_id = 9911
    insert_item(test_db, id=item_id, workflow_id="epic", status="planned")
    insert_epic_task(test_db, epic_id=item_id, task_num=1)

    def item_only(definition: dict[str, Any]) -> None:
        definition["policies"]["ownership"] = "single_item_claim"
        definition["policies"]["generated_children"] = "none"
        definition["policies"]["file_budget"] = "optional"

    target = _publish(
        test_db,
        "epic",
        label="Task-claim target",
        mutate=item_only,
    )
    _register(test_db, session_id="task-claim-writer")
    migration_conn, writer_conn = _connections(test_db)
    writer_started = threading.Event()
    writer_done = threading.Event()
    outcomes: dict[str, Any] = {}

    def acquire() -> None:
        writer_started.set()
        try:
            outcomes["writer"] = claim_work(
                writer_conn,
                session_id="task-claim-writer",
                target=make_epic_task_target(item_id, 1),
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["writer"] = exc
        finally:
            writer_done.set()

    writer = threading.Thread(target=acquire, name="task-claim-after-migration")
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
    assert isinstance(outcomes["writer"], SessionError)
    assert "does not permit epic-task claim lanes" in str(outcomes["writer"])


def test_reactivation_does_not_restore_a_claim_disallowed_by_new_pin(
    test_db: Any,
) -> None:
    _publish(test_db, "epic", label="Reactivation source")
    item_id = 9915
    insert_item(test_db, id=item_id, workflow_id="epic", status="planned")
    insert_epic_task(test_db, epic_id=item_id, task_num=1)
    _register(test_db, session_id="reactivation-writer")
    claim = claim_work(
        test_db,
        session_id="reactivation-writer",
        target=make_epic_task_target(item_id, 1),
    )
    test_db.execute(
        "UPDATE work_claims SET released_at=%s, "
        "release_reason='session_ended' WHERE id=%s",
        (iso8601_now(), int(claim["id"])),
    )
    test_db.commit()

    def item_only(definition: dict[str, Any]) -> None:
        definition["policies"]["ownership"] = "single_item_claim"
        definition["policies"]["generated_children"] = "none"
        definition["policies"]["file_budget"] = "optional"

    target = _publish(
        test_db,
        "epic",
        label="Reactivation target",
        mutate=item_only,
    )
    migrate_item_workflow_pin(
        test_db,
        item_id=item_id,
        target_version=int(target["version"]),
    )

    reacquired, conflicts = auto_reacquire_session_ended_claims(
        test_db,
        "reactivation-writer",
        reacquire_window_s=300,
    )

    assert reacquired == []
    assert (
        "does not permit epic-task claim lanes"
        in (conflicts[0]["invalid_target_reason"])
    )
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM work_claims WHERE epic_id=%s AND released_at IS NULL",
            (item_id,),
        ).fetchone()[0]
        == 0
    )


def _deployment_target(definition: dict[str, Any]) -> None:
    definition["policies"]["delivery"] = "after_merge_action"


def _deployment_fixture(test_db: Any, item_id: int, run_id: str) -> dict[str, Any]:
    _publish(test_db, "issue", label=f"{run_id} source")
    insert_item(
        test_db,
        id=item_id,
        workflow_id="issue",
        status="implemented",
    )
    insert_deployment_run(
        test_db,
        id=run_id,
        flow="binding-flow",
        status="created",
    )
    return _publish(
        test_db,
        "issue",
        label=f"{run_id} target",
        mutate=_deployment_target,
    )


def test_migration_first_rejects_new_run_membership_at_target_stage(
    test_db: Any,
    monkeypatch: Any,
) -> None:
    item_id = 9912
    run_id = "run-binding-migration"
    target = _deployment_fixture(test_db, item_id, run_id)
    migration_conn, writer_conn = _connections(test_db)
    monkeypatch.setattr(
        deployment_runs_crud_mutate,
        "connect",
        lambda _path=None: writer_conn,
    )
    writer_started = threading.Event()
    writer_done = threading.Event()
    outcomes: dict[str, Any] = {}

    def add_item() -> None:
        writer_started.set()
        try:
            outcomes["writer"] = deployment_runs_crud_mutate.cmd_add_item(
                run_id,
                item_id,
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["writer"] = exc
        finally:
            writer_done.set()

    writer = threading.Thread(target=add_item, name="run-member-after-migration")
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

    assert outcomes["migration"]["changed"] is True
    assert isinstance(outcomes["writer"], ValueError)
    assert "not delivery-ready" in str(outcomes["writer"])
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM deployment_run_items WHERE run_id=%s",
            (run_id,),
        ).fetchone()[0]
        == 0
    )


def test_active_run_restoration_revalidates_linked_item_pins(
    test_db: Any,
    monkeypatch: Any,
) -> None:
    item_id = 9913
    run_id = "run-binding-reactivation"
    target = _deployment_fixture(test_db, item_id, run_id)
    migrate_item_workflow_pin(
        test_db,
        item_id=item_id,
        target_version=int(target["version"]),
    )
    test_db.execute(
        "INSERT INTO deployment_run_items (run_id, item_id, added_at) "
        "VALUES (%s, %s, '2026-07-27T00:00:00Z')",
        (run_id, item_id),
    )
    test_db.execute(
        "UPDATE deployment_runs SET status='failed' WHERE id=%s",
        (run_id,),
    )
    test_db.commit()
    update_conn = connect_test_database(str(test_db.info.dbname))
    monkeypatch.setattr(
        deployment_runs_crud_mutate,
        "connect",
        lambda _path=None: update_conn,
    )

    error = deployment_runs_crud_mutate.cmd_update(
        run_id,
        "status",
        "executing",
    )

    assert error is not None
    assert "not delivery-ready" in error
    assert (
        test_db.execute(
            "SELECT status FROM deployment_runs WHERE id=%s",
            (run_id,),
        ).fetchone()[0]
        == "failed"
    )


def test_item_path_claim_rejects_task_scoped_current_pin(test_db: Any) -> None:
    _publish(test_db, "issue", label="Path binding source")
    item_id = 9914
    insert_item(test_db, id=item_id, workflow_id="issue", status="idea")

    def per_task(definition: dict[str, Any]) -> None:
        definition["policies"]["path_claims"] = "required_per_task"
        with_generated_epic_tasks(definition)

    target = _publish(
        test_db,
        "issue",
        label="Path binding target",
        mutate=per_task,
    )
    test_db.execute(
        "UPDATE items SET workflow_version_id=%s WHERE id=%s",
        (int(target["version_id"]), item_id),
    )
    test_db.commit()

    with pytest.raises(InvalidWorkflowBinding, match="task-scoped"):
        register_exception(
            test_db,
            actor_id=int(local_human(test_db)),
            integration_target="main",
            target_ids=[],
            exception_reason="no file changes",
            item_id=item_id,
        )
