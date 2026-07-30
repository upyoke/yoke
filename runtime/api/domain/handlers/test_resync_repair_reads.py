"""In-process integration coverage for the resync repair reads.

Exercises ``resync.item_lookup``, ``resync.epic_task_repair_read``, and
``resync.epic_task_body`` against a seeded Postgres authority. Each handler
is a thin wrapper over the same read the repair helper ran inline; these
tests prove the wrapper reads real DB rows server-side in its declared
response shape. This is the local / in-process leg of the ALL-MODES
contract; the relay leg is covered by ``test_resync_transport``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_epic_task, insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import resync_repair_reads as reads

TEST_ITEM_ID = 8600
TEST_EPIC_ID = 8610


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _global_req(function, *, payload):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-resync-repair-reads"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


class TestItemLookup:
    def test_found_returns_id_and_status(self, db):
        conn = connect_test_db(db)
        try:
            insert_item(
                conn, id=TEST_ITEM_ID, status="implementing",
                source=str(seed_human_actor(conn)),
            )
        finally:
            conn.close()
        outcome = reads.handle_item_lookup(
            _global_req(
                "resync.item_lookup", payload={"ref": str(TEST_ITEM_ID)}
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["found"] is True
        assert outcome.result_payload["id"] == TEST_ITEM_ID
        assert outcome.result_payload["status"] == "implementing"
        reads.ItemLookupResponse(**outcome.result_payload)

    def test_missing_is_not_found(self, db):
        outcome = reads.handle_item_lookup(
            _global_req("resync.item_lookup", payload={"ref": "999901"})
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload == {
            "found": False, "id": None, "status": None
        }

    def test_non_numeric_ref_is_not_found(self, db):
        # The text-cast match tolerates a non-numeric slug fragment; it
        # simply matches no row rather than erroring.
        outcome = reads.handle_item_lookup(
            _global_req("resync.item_lookup", payload={"ref": "not-a-number"})
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["found"] is False


class TestEpicTaskRepairRead:
    def _seed(self, db):
        conn = connect_test_db(db)
        try:
            insert_item(
                conn, id=TEST_EPIC_ID, workflow_id="epic",
                source=str(seed_human_actor(conn)),
            )
            insert_epic_task(
                conn, epic_id=TEST_EPIC_ID, task_num=2,
                title="Wire the adapter", status="implementing",
            )
        finally:
            conn.close()

    def test_returns_parent_and_task(self, db):
        self._seed(db)
        outcome = reads.handle_epic_task_repair_read(
            _global_req(
                "resync.epic_task_repair_read",
                payload={"epic_ref": str(TEST_EPIC_ID), "task_num": 2},
            )
        )
        assert outcome.primary_success, outcome.error
        payload = outcome.result_payload
        assert payload["parent_id"] == TEST_EPIC_ID
        assert payload["task_found"] is True
        assert payload["title"] == "Wire the adapter"
        assert payload["status"] == "implementing"
        reads.EpicTaskRepairReadResponse(**payload)

    def test_missing_task_reports_parent_only(self, db):
        self._seed(db)
        outcome = reads.handle_epic_task_repair_read(
            _global_req(
                "resync.epic_task_repair_read",
                payload={"epic_ref": str(TEST_EPIC_ID), "task_num": 99},
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["parent_id"] == TEST_EPIC_ID
        assert outcome.result_payload["task_found"] is False


class TestEpicTaskBody:
    def test_returns_body(self, db):
        conn = connect_test_db(db)
        try:
            insert_item(
                conn, id=TEST_EPIC_ID, workflow_id="epic",
                source=str(seed_human_actor(conn)),
            )
            insert_epic_task(
                conn, epic_id=TEST_EPIC_ID, task_num=1,
                body="## Plan\nDo the thing",
            )
        finally:
            conn.close()
        outcome = reads.handle_epic_task_body(
            _global_req(
                "resync.epic_task_body",
                payload={"epic_ref": str(TEST_EPIC_ID), "task_num": 1},
            )
        )
        assert outcome.primary_success, outcome.error
        assert "Do the thing" in outcome.result_payload["body"]
        reads.EpicTaskBodyResponse(**outcome.result_payload)
