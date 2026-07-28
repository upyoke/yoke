"""Workflow migration serialization with structured item cancellation."""

from __future__ import annotations

import io
import threading
from typing import Any

from runtime.api.domain.test_workflow_item_migration_compatibility import (
    ITEM_ID,
    _pin,
    _seed_path_claim,
)
from runtime.api.domain.test_workflow_item_migration_obligations import (
    _publish_policy_pair,
)
from runtime.api.fixtures.pg_testdb import connect_test_database
from yoke_core.domain import backlog_close_op
from yoke_core.domain.workflow_item_binding_lock import (
    lock_item_workflow_bindings,
)
from yoke_core.domain.workflow_item_versioning import (
    migrate_item_workflow_pin,
)


def test_migration_first_serializes_structured_cancellation(
    test_db,
    monkeypatch,
) -> None:
    _source, target = _publish_policy_pair(
        test_db,
        status="refined-idea",
    )
    _seed_path_claim(test_db)
    database = str(test_db.info.dbname)
    migration_conn = connect_test_database(database)
    close_conn = connect_test_database(database)
    monkeypatch.setattr(
        backlog_close_op,
        "connect",
        lambda _path=None: close_conn,
    )
    monkeypatch.setenv("YOKE_DRY_RUN", "1")
    close_started = threading.Event()
    close_done = threading.Event()
    outcomes: dict[str, Any] = {}

    def cancel_item() -> None:
        close_started.set()
        try:
            outcomes["close"] = backlog_close_op.execute_close(
                ITEM_ID,
                "obsolete",
                rebuild_board=False,
                out=io.StringIO(),
            )
        except BaseException as exc:  # noqa: BLE001 - thread evidence
            outcomes["close"] = exc
        finally:
            close_done.set()

    closer = threading.Thread(
        target=cancel_item,
        name="workflow-item-closer",
    )
    try:
        lock_item_workflow_bindings(migration_conn, (ITEM_ID,))
        closer.start()
        assert close_started.wait(timeout=10)
        assert not close_done.wait(timeout=0.2)
        outcomes["migration"] = migrate_item_workflow_pin(
            migration_conn,
            item_id=ITEM_ID,
            target_version=int(target["version"]),
        )
        closer.join(timeout=10)
        assert not closer.is_alive()
    except BaseException:
        migration_conn.rollback()
        closer.join(timeout=10)
        raise
    finally:
        migration_conn.close()

    assert not isinstance(outcomes["close"], BaseException)
    assert outcomes["close"]["success"] is True
    assert outcomes["migration"]["changed"] is True
    assert _pin(test_db) == (int(target["version_id"]), "cancelled")
