"""In-process integration coverage for the done-transition item/epic reads.

Exercises the ``done_transition.*`` item and epic internal handlers against a
seeded Postgres authority. Each handler is a thin wrapper over the unchanged
read the engine ran inline; these tests prove the wrapper reads real DB rows
server-side and returns the value in its declared response shape. This is the
local / in-process leg of the ALL-MODES contract; the relay leg is covered by
``test_done_transition_transport``.
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
from yoke_core.domain.handlers import done_transition_item_reads as reads
from yoke_core.domain.workflow_runtime import WorkflowRuntime


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _item_env(function, *, item_id, payload=None):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-done-reads"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload or {},
    )


def _global_env(function, *, payload):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-done-reads"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


class TestItemContext:
    def test_found_reconstructs_workflow_runtime(self, db):
        item_id = 8401
        conn = connect_test_db(db)
        try:
            insert_item(
                conn, id=item_id, title="Ship it", status="implementing",
                source=str(seed_human_actor(conn)),
            )
        finally:
            conn.close()
        outcome = reads.handle_item_context(
            _item_env("done_transition.item_context", item_id=item_id)
        )
        assert outcome.primary_success, outcome.error
        payload = outcome.result_payload
        assert payload["found"] is True
        assert payload["title"] == "Ship it"
        assert payload["stage_id"] == "implementing"
        assert payload["project"] == "yoke"
        reads.ItemContextResponse(**payload)
        # The serialized workflow reconstructs the exact runtime the runner uses.
        wf = payload["workflow"]
        runtime = WorkflowRuntime(
            workflow_id=wf["workflow_id"],
            workflow_version_id=wf["workflow_version_id"],
            version=wf["version"],
            definition_digest=wf["definition_digest"],
            definition=wf["definition"],
        )
        assert runtime.stage_ids  # a real definition round-tripped

    def test_missing_item_is_not_found(self, db):
        outcome = reads.handle_item_context(
            _item_env("done_transition.item_context", item_id=999901)
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload == {"found": False}


class TestItemField:
    @pytest.mark.parametrize(
        "field,column_kwargs,expected",
        [
            ("deployment_flow", {"deployment_flow": "yoke-hosted-stage"},
             "yoke-hosted-stage"),
            ("status", {"status": "implemented"}, "implemented"),
            ("merged_at", {"merged_at": "2026-01-02T03:04:05Z"},
             "2026-01-02T03:04:05Z"),
            ("deploy_stage", {"deploy_stage": "complete"}, "complete"),
        ],
    )
    def test_reads_column_value(self, db, field, column_kwargs, expected):
        item_id = 8410
        conn = connect_test_db(db)
        try:
            insert_item(
                conn, id=item_id, source=str(seed_human_actor(conn)),
                **column_kwargs,
            )
        finally:
            conn.close()
        outcome = reads.handle_item_field(
            _item_env("done_transition.item_field", item_id=item_id,
                      payload={"field": field})
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["value"] == expected
        reads.ItemFieldResponse(**outcome.result_payload)

    def test_project_resolves_slug(self, db):
        item_id = 8411
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
        finally:
            conn.close()
        outcome = reads.handle_item_field(
            _item_env("done_transition.item_field", item_id=item_id,
                      payload={"field": "project"})
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["value"] == "yoke"

    def test_missing_row_is_empty_string(self, db):
        outcome = reads.handle_item_field(
            _item_env("done_transition.item_field", item_id=999902,
                      payload={"field": "status"})
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["value"] == ""

    def test_unsupported_field_rejected(self, db):
        outcome = reads.handle_item_field(
            _item_env("done_transition.item_field", item_id=8412,
                      payload={"field": "title"})
        )
        assert not outcome.primary_success
        assert outcome.error.code == "payload_invalid"


class TestBlockedGate:
    def test_not_blocked_when_flag_clear(self, db):
        item_id = 8420
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
        finally:
            conn.close()
        outcome = reads.handle_blocked_gate(
            _item_env("done_transition.blocked_gate", item_id=item_id)
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["blocked"] is False
        reads.BlockedGateResponse(**outcome.result_payload)

    def test_blocked_reports_reason(self, db):
        item_id = 8421
        conn = connect_test_db(db)
        try:
            insert_item(
                conn, id=item_id, source=str(seed_human_actor(conn)),
                blocked=1, blocked_reason="upstream unresolved",
            )
        finally:
            conn.close()
        outcome = reads.handle_blocked_gate(
            _item_env("done_transition.blocked_gate", item_id=item_id)
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["blocked"] is True
        assert outcome.result_payload["reason"] == "upstream unresolved"


class TestEpicReads:
    def _seed_epic(self, db, epic_id):
        conn = connect_test_db(db)
        try:
            insert_item(
                conn, id=epic_id, workflow_id="epic",
                source=str(seed_human_actor(conn)),
            )
            insert_epic_task(
                conn, epic_id=epic_id, task_num=1, status="reviewed-implementation",
                github_issue="#701",
            )
            insert_epic_task(
                conn, epic_id=epic_id, task_num=2, status="implementing",
            )
        finally:
            conn.close()

    def test_task_list_returns_pipe_rows(self, db):
        epic_id = 8430
        self._seed_epic(db, epic_id)
        outcome = reads.handle_epic_task_list(
            _global_env("done_transition.epic_task_list",
                        payload={"epic_id": str(epic_id)})
        )
        assert outcome.primary_success, outcome.error
        listing = outcome.result_payload["task_list"]
        assert "reviewed-implementation" in listing
        assert "implementing" in listing
        reads.EpicTaskListResponse(**outcome.result_payload)

    def test_task_list_empty_epic(self, db):
        epic_id = 8431
        conn = connect_test_db(db)
        try:
            insert_item(
                conn, id=epic_id, workflow_id="epic",
                source=str(seed_human_actor(conn)),
            )
        finally:
            conn.close()
        outcome = reads.handle_epic_task_list(
            _global_env("done_transition.epic_task_list",
                        payload={"epic_id": str(epic_id)})
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["task_list"] == ""

    def test_github_issues_map(self, db):
        epic_id = 8432
        self._seed_epic(db, epic_id)
        outcome = reads.handle_epic_task_github_issues(
            _global_env(
                "done_transition.epic_task_github_issues",
                payload={"epic_id": str(epic_id), "task_nums": ["1", "2"]},
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["github_issues"] == {"1": "#701", "2": ""}
        reads.EpicTaskGithubIssuesResponse(**outcome.result_payload)
