"""Concurrent migration receipts describe each committed pin exactly."""

from __future__ import annotations

from copy import deepcopy
import threading
from typing import Any

from runtime.api.fixtures.backlog import insert_item
from runtime.api.fixtures.pg_testdb import connect_test_database
from yoke_core.domain.builtin_workflow_definitions import (
    builtin_workflow_definition,
)
from yoke_core.domain import workflow_item_versioning
from yoke_core.domain.workflow_item_versioning import migrate_item_workflow_pin
from yoke_core.domain.workflow_registry import publish_workflow_version


def _publish(test_db: Any, label: str) -> dict[str, Any]:
    definition = deepcopy(builtin_workflow_definition("issue")["definition"])
    definition["stages"][0]["label"] = label
    definition["policies"]["path_claims"] = "optional"
    return publish_workflow_version(
        test_db,
        workflow_id="issue",
        definition=definition,
    )


def test_two_migrators_return_the_pin_owned_by_each_transaction(
    test_db: Any,
    monkeypatch: Any,
) -> None:
    source = _publish(test_db, "Receipt source")
    insert_item(test_db, id=9871, workflow_id="issue", status="idea")
    middle = _publish(test_db, "Receipt middle")
    target = _publish(test_db, "Receipt target")
    db_name = str(test_db.info.dbname)
    first_conn = connect_test_database(db_name)
    second_conn = connect_test_database(db_name)
    first_receipt_ready = threading.Event()
    allow_first_commit = threading.Event()
    second_started = threading.Event()
    second_done = threading.Event()
    receipts: dict[str, Any] = {}
    original_inspect = workflow_item_versioning._inspect_item_workflow_pin

    def pause_middle_receipt(
        conn: Any,
        item_id: int,
        runtime: Any,
    ) -> dict[str, Any]:
        receipt = original_inspect(conn, item_id, runtime)
        if int(runtime.workflow_version_id) == int(middle["version_id"]):
            first_receipt_ready.set()
            assert allow_first_commit.wait(timeout=10)
        return receipt

    monkeypatch.setattr(
        workflow_item_versioning,
        "_inspect_item_workflow_pin",
        pause_middle_receipt,
    )

    def migrate_first() -> None:
        receipts["first"] = migrate_item_workflow_pin(
            first_conn,
            item_id=9871,
            target_version=int(middle["version"]),
        )

    def migrate_second() -> None:
        second_started.set()
        try:
            receipts["second"] = migrate_item_workflow_pin(
                second_conn,
                item_id=9871,
                target_version=int(target["version"]),
            )
        finally:
            second_done.set()

    first = threading.Thread(target=migrate_first, name="receipt-migration-one")
    second = threading.Thread(target=migrate_second, name="receipt-migration-two")
    try:
        first.start()
        assert first_receipt_ready.wait(timeout=10)
        second.start()
        assert second_started.wait(timeout=10)
        assert not second_done.wait(timeout=0.2)
        allow_first_commit.set()
        first.join(timeout=10)
        second.join(timeout=10)
        assert not first.is_alive()
        assert not second.is_alive()
    finally:
        allow_first_commit.set()
        first_conn.close()
        second_conn.close()

    assert receipts["first"]["before"]["workflow_version_id"] == source["version_id"]
    assert receipts["first"]["after"]["workflow_version_id"] == middle["version_id"]
    assert receipts["second"]["before"]["workflow_version_id"] == middle["version_id"]
    assert receipts["second"]["after"]["workflow_version_id"] == target["version_id"]
    final_pin = test_db.execute(
        "SELECT workflow_version_id FROM items WHERE id=9871"
    ).fetchone()[0]
    assert int(final_pin) == int(target["version_id"])
