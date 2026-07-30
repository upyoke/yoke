"""In-process integration coverage for the resync Stage-2 prefetch.

Exercises ``resync.compare_prefetch`` against a seeded Postgres authority.
The handler is a thin wrapper over the engine's inline prefetch; this test
proves it reads real items + epic-tasks server-side, renders each item's
body, and resolves the merge-implied flag to a plain bool the engine
consumes. This is the local / in-process leg of the ALL-MODES contract;
the relay leg is covered by ``test_resync_transport``.
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
from yoke_core.domain.handlers import resync_compare_reads as reads

TEST_ITEM_ID = 8800
TEST_EPIC_ID = 8810


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _prefetch_req():
    return FunctionCallRequest(
        function="resync.compare_prefetch",
        actor=ActorContext(actor_id=None, session_id="s-resync-compare"),
        target=TargetRef(kind="global"),
        payload={},
    )


def test_prefetch_items_and_epic_tasks(db):
    conn = connect_test_db(db)
    try:
        actor = str(seed_human_actor(conn))
        insert_item(
            conn, id=TEST_ITEM_ID, title="Compare me",
            status="implementing", source=actor,
        )
        insert_item(
            conn, id=TEST_EPIC_ID, workflow_id="epic", source=actor,
        )
        insert_epic_task(
            conn, epic_id=TEST_EPIC_ID, task_num=1, title="Task one",
            status="implementing", body="task body",
        )
    finally:
        conn.close()

    outcome = reads.handle_compare_prefetch(_prefetch_req())
    assert outcome.primary_success, outcome.error
    payload = outcome.result_payload
    reads.ComparePrefetchResponse(**payload)

    items = {row["id"]: row for row in payload["items"]}
    assert TEST_ITEM_ID in items, "prefetch should include the seeded item"
    item = items[TEST_ITEM_ID]
    assert item["title"] == "Compare me"
    assert item["status"] == "implementing"
    # The merge-implied flag is resolved server-side to a plain bool.
    assert isinstance(item["implies_merge"], bool)
    # Actor labels + rendered body are present (the fields the comparator reads).
    assert "source_label" in item
    assert "owner_label" in item
    assert isinstance(item["body"], str)

    tasks = {(str(row["epic_id"]), row["task_num"]): row
             for row in payload["epic_tasks"]}
    assert (str(TEST_EPIC_ID), 1) in tasks
    assert tasks[(str(TEST_EPIC_ID), 1)]["body"] == "task body"
