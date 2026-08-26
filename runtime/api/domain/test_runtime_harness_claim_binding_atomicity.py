"""PostgreSQL serialization proof for the live runtime claim command."""

from __future__ import annotations

from copy import deepcopy
import threading
from typing import Any

import pytest

from runtime.api.fixtures.backlog import insert_epic_task, insert_item
from runtime.api.domain.test_workflow_item_migration_compatibility import (
    ITEM_ID,
    _pin,
    _publish_pair,
)
from runtime.api.fixtures.pg_testdb import connect_test_database
from runtime.api.test_sessions import _register
from yoke_core.hooks import sessions_claims_acquire as runtime_claims
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.workflow_definition_codec import WorkflowRegistryError
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)
from yoke_core.domain.workflow_item_versioning import migrate_item_workflow_pin
from yoke_core.domain.workflow_registry import publish_workflow_version
from yoke_core.domain.work_claim_targets import decode_scope, make_item_target


def _join(worker: threading.Thread) -> None:
    worker.join(timeout=10)
    assert not worker.is_alive(), f"thread {worker.name} did not finish"


def _publish_runtime_claim_pair(test_db, *, target_kind: str) -> tuple[dict, dict]:
    if target_kind == "item":
        return _publish_pair(test_db, case="work_claim")

    source_definition = deepcopy(builtin_workflow_definition("epic")["definition"])
    source_definition["stages"][0]["label"] = "Runtime claim source"
    source_definition["policies"]["path_claims"] = "optional"
    source = publish_workflow_version(
        test_db,
        workflow_id="epic",
        definition=source_definition,
    )
    insert_item(
        test_db,
        id=ITEM_ID,
        workflow_id="epic",
        status="implementing",
    )
    insert_epic_task(
        test_db,
        epic_id=ITEM_ID,
        task_num=1,
        title="Runtime claim task",
        status="implementing",
    )

    target_definition = deepcopy(source_definition)
    target_definition["stages"][0]["label"] = "Runtime claim target"
    target_definition["policies"]["ownership"] = "exclusive_session_work_claim"
    target = publish_workflow_version(
        test_db,
        workflow_id="epic",
        definition=target_definition,
    )
    return source, target


@pytest.mark.parametrize(
    ("target_kind", "claim_kwargs", "target_label"),
    (
        ("item", {"item_id": ITEM_ID}, f"YOK-{ITEM_ID}"),
        (
            "epic_task",
            {"epic_id": ITEM_ID, "task_num": 1},
            f"YOK-{ITEM_ID} task 1",
        ),
    ),
)
def test_runtime_claim_lands_before_incompatible_migration_review(
    test_db,
    monkeypatch,
    target_kind: str,
    claim_kwargs: dict[str, int],
    target_label: str,
) -> None:
    """A runtime claim holding the parent lock cannot be missed by migration."""
    source, target = _publish_runtime_claim_pair(
        test_db,
        target_kind=target_kind,
    )
    _register(test_db, session_id="runtime-claim-session")
    database_name = str(test_db.info.dbname)
    claim_conn = connect_test_database(database_name)
    migration_conn = connect_test_database(database_name)
    claim_locked = threading.Event()
    finish_claim = threading.Event()
    migration_started = threading.Event()
    migration_done = threading.Event()
    outcomes: dict[str, Any] = {}
    original_lock = runtime_claims.binding_lock.lock_work_claim_target_workflow_binding

    def pause_after_parent_lock(conn: Any, target: Any) -> tuple[int, ...]:
        locked = original_lock(conn, target)
        claim_locked.set()
        assert finish_claim.wait(timeout=10)
        return locked

    monkeypatch.setattr(
        runtime_claims.binding_lock,
        "lock_work_claim_target_workflow_binding",
        pause_after_parent_lock,
    )

    def acquire() -> None:
        try:
            outcomes["claim"] = runtime_claims.cmd_claim(
                claim_conn,
                "runtime-claim-session",
                target_kind,
                **claim_kwargs,
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["claim"] = exc

    def migrate() -> None:
        migration_started.set()
        try:
            outcomes["migration"] = migrate_item_workflow_pin(
                migration_conn,
                item_id=ITEM_ID,
                target_version=int(target["version"]),
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["migration"] = exc
        finally:
            migration_done.set()

    claimer = threading.Thread(target=acquire, name="runtime-claim-writer")
    migrator = threading.Thread(target=migrate, name="workflow-migrator")
    try:
        claimer.start()
        assert claim_locked.wait(timeout=10)
        migrator.start()
        assert migration_started.wait(timeout=10)
        assert not migration_done.wait(timeout=0.2)
        finish_claim.set()
        _join(claimer)
        _join(migrator)
    finally:
        finish_claim.set()
        claim_conn.close()
        migration_conn.close()

    assert outcomes["claim"] == (f"Claimed: {target_label} by runtime-claim-session")
    migration_error = outcomes["migration"]
    assert isinstance(migration_error, WorkflowRegistryError)
    assert "live work claims" in str(migration_error)
    assert _pin(test_db) == (int(source["version_id"]), "implementing")
    live_claims = test_db.execute(
        "SELECT session_id, target_kind, scope "
        "FROM work_claims WHERE released_at IS NULL",
    ).fetchall()
    assert len(live_claims) == 1
    assert live_claims[0][0] == "runtime-claim-session"
    assert live_claims[0][1] == target_kind
    scope = decode_scope(live_claims[0][2])
    parent_key = "item_id" if target_kind == "item" else "epic_id"
    assert int(scope[parent_key]) == ITEM_ID
    if target_kind == "epic_task":
        assert int(scope["task_num"]) == 1


def test_stale_cleanup_finishes_before_migration_first_parent_lock_wait(
    test_db,
    monkeypatch,
) -> None:
    """Stale-row cleanup cannot hold a claim lock while waiting on the item."""
    _source, target = _publish_pair(test_db)
    _register(test_db, session_id="stale-runtime-holder")
    _register(test_db, session_id="runtime-successor")
    runtime_claims.cmd_claim(
        test_db,
        "stale-runtime-holder",
        "item",
        item_id=ITEM_ID,
    )
    test_db.execute(
        "UPDATE harness_sessions SET ended_at=%s "
        "WHERE session_id='stale-runtime-holder'",
        (iso8601_now(),),
    )
    test_db.commit()

    database_name = str(test_db.info.dbname)
    migration_conn = connect_test_database(database_name)
    claim_conn = connect_test_database(database_name)
    about_to_lock_parent = threading.Event()
    outcomes: dict[str, Any] = {}
    original_lock = runtime_claims.binding_lock.lock_work_claim_target_workflow_binding

    def observe_parent_lock(conn: Any, target: Any) -> tuple[int, ...]:
        about_to_lock_parent.set()
        return original_lock(conn, target)

    monkeypatch.setattr(
        runtime_claims.binding_lock,
        "lock_work_claim_target_workflow_binding",
        observe_parent_lock,
    )

    def acquire() -> None:
        try:
            outcomes["claim"] = runtime_claims.cmd_claim(
                claim_conn,
                "runtime-successor",
                "item",
                item_id=ITEM_ID,
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["claim"] = exc

    claimer = threading.Thread(target=acquire, name="stale-runtime-reclaimer")
    try:
        lock_item_workflow_bindings(migration_conn, (ITEM_ID,))
        claimer.start()
        assert about_to_lock_parent.wait(timeout=10)
        stale_row = test_db.execute(
            "SELECT released_at FROM work_claims "
            "WHERE session_id='stale-runtime-holder' "
            "AND target_kind='item' AND scope=%s",
            (make_item_target(ITEM_ID).scope_json(),),
        ).fetchone()
        assert stale_row[0] is not None
        outcomes["migration"] = migrate_item_workflow_pin(
            migration_conn,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )
        _join(claimer)
    except BaseException:
        migration_conn.rollback()
        _join(claimer)
        raise
    finally:
        migration_conn.close()
        claim_conn.close()

    assert outcomes["migration"]["changed"] is True
    assert outcomes["claim"] == (f"Claimed: YOK-{ITEM_ID} by runtime-successor")
    assert _pin(test_db) == (int(target["version_id"]), "implementing")
    active_rows = test_db.execute(
        "SELECT session_id FROM work_claims WHERE target_kind='item' "
        "AND scope=%s AND released_at IS NULL",
        (make_item_target(ITEM_ID).scope_json(),),
    ).fetchall()
    assert [row[0] for row in active_rows] == ["runtime-successor"]


def test_process_claim_retains_public_response_without_item_parent(test_db) -> None:
    _register(test_db, session_id="runtime-process-session")

    result = runtime_claims.cmd_claim(
        test_db,
        "runtime-process-session",
        "process",
        process_key="strategy:yoke",
        conflict_group="strategy:yoke",
    )

    assert result == "Claimed: process:strategy:yoke by runtime-process-session"
    row = test_db.execute(
        "SELECT target_kind, scope "
        "FROM work_claims WHERE session_id='runtime-process-session' "
        "AND released_at IS NULL"
    ).fetchone()
    assert row[0] == "process"
    assert decode_scope(row[1]) == {
        "conflict_group": "strategy:yoke",
        "process_key": "strategy:yoke",
    }


def test_runtime_claim_rejects_terminal_item_after_parent_lock(test_db) -> None:
    _publish_pair(test_db)
    _register(test_db, session_id="runtime-terminal-session")
    test_db.execute(
        "UPDATE items SET status='done' WHERE id=%s",
        (ITEM_ID,),
    )
    test_db.commit()

    with pytest.raises(PermissionError, match="terminal"):
        runtime_claims.cmd_claim(
            test_db,
            "runtime-terminal-session",
            "item",
            item_id=ITEM_ID,
        )
    count = test_db.execute(
        "SELECT COUNT(*) FROM work_claims "
        "WHERE session_id='runtime-terminal-session' "
        "AND released_at IS NULL",
    ).fetchone()[0]
    assert int(count) == 0


def test_runtime_claim_rejects_nonexistent_item(test_db) -> None:
    _register(test_db, session_id="runtime-missing-item-session")

    with pytest.raises(PermissionError, match="does not exist"):
        runtime_claims.cmd_claim(
            test_db,
            "runtime-missing-item-session",
            "item",
            item_id=999_999,
        )
    count = test_db.execute(
        "SELECT COUNT(*) FROM work_claims "
        "WHERE session_id='runtime-missing-item-session' "
        "AND released_at IS NULL",
    ).fetchone()[0]
    assert int(count) == 0
