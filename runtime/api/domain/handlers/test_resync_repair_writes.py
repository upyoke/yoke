"""In-process integration coverage for the resync repair write.

Exercises ``resync.epic_task_github_issue_set`` against a seeded Postgres
authority. The handler is a thin wrapper over the unchanged
``task_update_field`` write the repair helper ran inline; this test proves
the wrapper writes the new issue reference into the real ``github_issue``
column server-side. This is the local / in-process leg of the ALL-MODES
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
from yoke_core.domain.handlers import resync_repair_writes as writes

TEST_EPIC_ID = 8500


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _write_req(*, item_id, payload):
    return FunctionCallRequest(
        function="resync.epic_task_github_issue_set",
        actor=ActorContext(actor_id=None, session_id="s-resync-writes"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def test_writes_github_issue_field(db):
    conn = connect_test_db(db)
    try:
        insert_item(
            conn, id=TEST_EPIC_ID, workflow_id="epic",
            source=str(seed_human_actor(conn)),
        )
        insert_epic_task(
            conn, epic_id=TEST_EPIC_ID, task_num=1, github_issue="#1",
        )
    finally:
        conn.close()

    outcome = writes.handle_epic_task_github_issue_set(
        _write_req(
            item_id=TEST_EPIC_ID,
            payload={
                "epic_ref": str(TEST_EPIC_ID),
                "task_num": 1,
                "issue_ref": "#999",
            },
        )
    )
    assert outcome.primary_success, outcome.error
    assert outcome.result_payload == {"updated": True}
    writes.EpicTaskGithubIssueSetResponse(**outcome.result_payload)

    conn = connect_test_db(db)
    try:
        row = conn.execute(
            "SELECT github_issue FROM epic_tasks "
            "WHERE epic_id = %s AND task_num = %s",
            (TEST_EPIC_ID, 1),
        ).fetchone()
    finally:
        conn.close()
    assert row[0] == "#999"


def test_missing_task_surfaces_error(db):
    outcome = writes.handle_epic_task_github_issue_set(
        _write_req(
            item_id=999900,
            payload={"epic_ref": "999900", "task_num": 7, "issue_ref": "#5"},
        )
    )
    # The unchanged write raises LookupError for a missing task; the handler
    # surfaces it as a structured error so the caller degrades (advisory).
    assert not outcome.primary_success
    assert outcome.error is not None
