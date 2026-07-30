"""In-process integration coverage for the resync Stage-1 linkage reads.

Exercises ``resync.linkage_roster`` and ``resync.linkage_rows`` against a
seeded Postgres authority. Each handler is a thin wrapper over the same
queries the engine ran inline; these tests prove the wrappers read real DB
rows server-side. This is the local / in-process leg of the ALL-MODES
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
from yoke_core.domain.handlers import resync_detect_reads as reads

TEST_ITEM_ID = 8700
TEST_EPIC_ID = 8710


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _global_req(function, *, payload):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-resync-detect-reads"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _seed(db):
    conn = connect_test_db(db)
    try:
        actor = str(seed_human_actor(conn))
        insert_item(
            conn, id=TEST_ITEM_ID, project="yoke", github_issue="#41",
            source=actor,
        )
        insert_item(
            conn, id=TEST_EPIC_ID, project="yoke", workflow_id="epic",
            source=actor,
        )
        insert_epic_task(
            conn, epic_id=TEST_EPIC_ID, task_num=1, title="Task one",
            github_issue="#42",
        )
    finally:
        conn.close()


class TestLinkageRoster:
    def test_roster_includes_backlog_project(self, db):
        _seed(db)
        outcome = reads.handle_linkage_roster(
            _global_req("resync.linkage_roster", payload={"project": ""})
        )
        assert outcome.primary_success, outcome.error
        payload = outcome.result_payload
        reads.LinkageRosterResponse(**payload)
        assert isinstance(payload["fetch_projects"], list)
        assert isinstance(payload["sync_disabled"], dict)
        # The yoke project (drawn from the seeded backlog) is in the roster,
        # either enabled (fetch) or sync-disabled.
        roster = set(payload["fetch_projects"]) | set(payload["sync_disabled"])
        assert "yoke" in roster

    def test_explicit_project_scopes_roster(self, db):
        _seed(db)
        outcome = reads.handle_linkage_roster(
            _global_req("resync.linkage_roster", payload={"project": "yoke"})
        )
        assert outcome.primary_success, outcome.error
        roster = set(outcome.result_payload["fetch_projects"]) | set(
            outcome.result_payload["sync_disabled"]
        )
        assert roster == {"yoke"}


class TestLinkageRows:
    def test_backlog_and_task_rows(self, db):
        _seed(db)
        outcome = reads.handle_linkage_rows(
            _global_req("resync.linkage_rows", payload={"project": ""})
        )
        assert outcome.primary_success, outcome.error
        payload = outcome.result_payload
        reads.LinkageRowsResponse(**payload)
        backlog_ids = {row[0]: row[1] for row in payload["backlog_rows"]}
        assert backlog_ids.get(TEST_ITEM_ID) == "#41"
        task_rows = {
            (str(row[0]), row[1]): row[3] for row in payload["task_rows"]
        }
        assert task_rows.get((str(TEST_EPIC_ID), 1)) == "#42"

    def test_project_filter_scopes_rows(self, db):
        _seed(db)
        outcome = reads.handle_linkage_rows(
            _global_req("resync.linkage_rows", payload={"project": "yoke"})
        )
        assert outcome.primary_success, outcome.error
        backlog_ids = {row[0] for row in outcome.result_payload["backlog_rows"]}
        assert TEST_ITEM_ID in backlog_ids
