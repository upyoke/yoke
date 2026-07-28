"""Two-connection proof for item workflow migration serialization."""

from __future__ import annotations

import threading
from typing import Any

from runtime.api.domain.test_workflow_item_migration_compatibility import (
    ITEM_ID,
    _pin,
    _seed_delivery,
    _seed_path_claim,
    _seed_work_claim,
)
from runtime.api.domain.test_workflow_item_migration_obligations import (
    _publish_policy_pair,
)
from runtime.api.fixtures.pg_testdb import connect_test_database
from yoke_core.domain.item_worktrees import record_item_worktree
from yoke_core.domain import deployment_runs_crud_mutate
from yoke_core.domain.path_claims import cancel, release
from yoke_core.domain.sessions_lifecycle_claim_release import release_claim_by_id
from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)
from yoke_core.domain.workflow_item_versioning import (
    migrate_item_workflow_pin,
)


def _connections(test_db) -> tuple[Any, Any]:
    name = str(test_db.info.dbname)
    return connect_test_database(name), connect_test_database(name)


def _join(thread: threading.Thread) -> None:
    thread.join(timeout=10)
    assert not thread.is_alive(), f"thread {thread.name} did not finish"


def test_writer_first_forces_migration_to_observe_new_incompatible_lane(
    test_db,
) -> None:
    source, target = _publish_policy_pair(
        test_db,
        status="refined-idea",
        target_worktrees="worker_and_integration_lanes",
    )
    _seed_path_claim(test_db)
    writer_conn, migration_conn = _connections(test_db)
    writer_ready = threading.Event()
    release_writer = threading.Event()
    migration_started = threading.Event()
    migration_done = threading.Event()
    outcomes: dict[str, BaseException | None] = {}

    def write_lane() -> None:
        try:
            record_item_worktree(
                writer_conn,
                item_id=ITEM_ID,
                branch="codex/writer-first",
                path=None,
                lane_role="implementation",
            )
            writer_ready.set()
            assert release_writer.wait(timeout=10)
            writer_conn.commit()
            outcomes["writer"] = None
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            writer_conn.rollback()
            outcomes["writer"] = exc
            writer_ready.set()

    def migrate() -> None:
        assert writer_ready.wait(timeout=10)
        migration_started.set()
        try:
            migrate_item_workflow_pin(
                migration_conn,
                item_id=ITEM_ID,
                target_version=int(target["version"]),
            )
            outcomes["migration"] = None
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["migration"] = exc
        finally:
            migration_done.set()

    writer = threading.Thread(target=write_lane, name="workflow-lane-writer")
    migrator = threading.Thread(target=migrate, name="workflow-migrator")
    try:
        writer.start()
        assert writer_ready.wait(timeout=10)
        migrator.start()
        assert migration_started.wait(timeout=10)
        assert not migration_done.wait(timeout=0.2)
        release_writer.set()
        _join(writer)
        _join(migrator)
    finally:
        release_writer.set()
        writer_conn.close()
        migration_conn.close()

    assert outcomes["writer"] is None
    assert isinstance(outcomes["migration"], WorkflowRegistryError)
    assert "active worktree lanes" in str(outcomes["migration"])
    assert _pin(test_db) == (int(source["version_id"]), "refined-idea")


def test_migration_first_forces_writer_to_validate_target_policy(test_db) -> None:
    _source, target = _publish_policy_pair(
        test_db,
        status="refined-idea",
        target_worktrees="worker_and_integration_lanes",
    )
    _seed_path_claim(test_db)
    migration_conn, writer_conn = _connections(test_db)
    migration_locked = threading.Event()
    writer_started = threading.Event()
    writer_done = threading.Event()
    outcomes: dict[str, BaseException | None] = {}

    def write_lane() -> None:
        writer_started.set()
        try:
            record_item_worktree(
                writer_conn,
                item_id=ITEM_ID,
                branch="codex/migration-first",
                path=None,
                lane_role="implementation",
            )
            writer_conn.commit()
            outcomes["writer"] = None
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            writer_conn.rollback()
            outcomes["writer"] = exc
        finally:
            writer_done.set()

    writer = threading.Thread(target=write_lane, name="target-policy-writer")
    try:
        lock_item_workflow_bindings(migration_conn, (ITEM_ID,))
        migration_locked.set()
        writer.start()
        assert migration_locked.is_set()
        assert writer_started.wait(timeout=10)
        assert not writer_done.wait(timeout=0.2)
        outcomes["migration"] = None
        migrate_item_workflow_pin(
            migration_conn,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )
        _join(writer)
    except BaseException as exc:  # noqa: BLE001 - preserve cleanup evidence
        outcomes["migration"] = exc
        migration_conn.rollback()
        _join(writer)
    finally:
        migration_conn.close()
        writer_conn.close()

    assert outcomes["migration"] is None
    assert isinstance(outcomes["writer"], ValueError)
    assert "does not allow 'implementation'" in str(outcomes["writer"])
    assert _pin(test_db) == (int(target["version_id"]), "refined-idea")
    lane_count = test_db.execute(
        "SELECT COUNT(*) FROM item_worktrees WHERE item_id = %s",
        (ITEM_ID,),
    ).fetchone()[0]
    assert int(lane_count) == 0


def test_idempotent_path_claim_terminal_calls_release_parent_lock(test_db) -> None:
    _publish_policy_pair(test_db, status="refined-idea")
    _seed_path_claim(test_db)
    _seed_path_claim(test_db)
    claim_ids = tuple(
        int(row[0])
        for row in test_db.execute(
            "SELECT id FROM path_claims WHERE owner_item_id = %s ORDER BY id",
            (ITEM_ID,),
        ).fetchall()
    )
    release(test_db, claim_id=claim_ids[0], reason="initial release")
    cancel(test_db, claim_id=claim_ids[1], reason="initial cancel")

    for operation, claim_id in (
        (release, claim_ids[0]),
        (cancel, claim_ids[1]),
    ):
        terminal_conn, competing_conn = _connections(test_db)
        try:
            operation(
                terminal_conn,
                claim_id=claim_id,
                reason="idempotent retry",
            )
            competing_conn.execute("SET LOCAL lock_timeout = '1s'")
            assert lock_item_workflow_bindings(competing_conn, (ITEM_ID,)) == (ITEM_ID,)
            competing_conn.rollback()
        finally:
            terminal_conn.close()
            competing_conn.close()


def test_migration_first_serializes_work_claim_release(test_db) -> None:
    _source, target = _publish_policy_pair(test_db)
    _seed_path_claim(test_db)
    _seed_work_claim(test_db)
    claim_id = int(
        test_db.execute(
            "SELECT id FROM work_claims WHERE epic_id = %s AND released_at IS NULL",
            (ITEM_ID,),
        ).fetchone()[0]
    )
    migration_conn, release_conn = _connections(test_db)
    release_started = threading.Event()
    release_done = threading.Event()
    outcomes: dict[str, Any] = {}

    def release_binding() -> None:
        release_started.set()
        try:
            outcomes["release"] = release_claim_by_id(
                release_conn,
                claim_id,
                reason="migration serialization proof",
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["release"] = exc
        finally:
            release_done.set()

    releaser = threading.Thread(
        target=release_binding,
        name="workflow-work-claim-releaser",
    )
    try:
        lock_item_workflow_bindings(migration_conn, (ITEM_ID,))
        releaser.start()
        assert release_started.wait(timeout=10)
        assert not release_done.wait(timeout=0.2)
        outcomes["migration"] = migrate_item_workflow_pin(
            migration_conn,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )
        _join(releaser)
    except BaseException:
        migration_conn.rollback()
        _join(releaser)
        raise
    finally:
        migration_conn.close()
        release_conn.close()

    assert not isinstance(outcomes["release"], BaseException)
    assert outcomes["migration"]["changed"] is True
    assert _pin(test_db) == (int(target["version_id"]), "implementing")
    assert (
        test_db.execute(
            "SELECT released_at FROM work_claims WHERE id = %s",
            (claim_id,),
        ).fetchone()[0]
        is not None
    )


def test_migration_first_serializes_deployment_membership_removal(
    test_db,
    monkeypatch,
) -> None:
    _source, target = _publish_policy_pair(test_db)
    _seed_path_claim(test_db)
    _seed_delivery(test_db)
    test_db.execute(
        "UPDATE deployment_runs SET status = 'created' WHERE id = %s",
        ("run-migration",),
    )
    test_db.commit()
    migration_conn, removal_conn = _connections(test_db)
    monkeypatch.setattr(
        deployment_runs_crud_mutate,
        "connect",
        lambda _path=None: removal_conn,
    )
    removal_started = threading.Event()
    removal_done = threading.Event()
    outcomes: dict[str, Any] = {}

    def remove_binding() -> None:
        removal_started.set()
        try:
            outcomes["remove"] = deployment_runs_crud_mutate.cmd_remove_item(
                "run-migration",
                ITEM_ID,
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["remove"] = exc
        finally:
            removal_done.set()

    remover = threading.Thread(
        target=remove_binding,
        name="workflow-deployment-membership-remover",
    )
    try:
        lock_item_workflow_bindings(migration_conn, (ITEM_ID,))
        remover.start()
        assert removal_started.wait(timeout=10)
        assert not removal_done.wait(timeout=0.2)
        outcomes["migration"] = migrate_item_workflow_pin(
            migration_conn,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )
        _join(remover)
    except BaseException:
        migration_conn.rollback()
        _join(remover)
        raise
    finally:
        migration_conn.close()

    assert not isinstance(outcomes["remove"], BaseException)
    assert outcomes["migration"]["changed"] is True
    assert (
        test_db.execute(
            "SELECT COUNT(*) FROM deployment_run_items "
            "WHERE run_id = %s AND item_id = %s",
            ("run-migration", ITEM_ID),
        ).fetchone()[0]
        == 0
    )
