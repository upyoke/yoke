# ruff: noqa: F811
"""In-process integration coverage for the done-transition status flips.

Exercises the two ``done_transition.*`` internal status-write handlers against
a seeded Postgres authority. Each posts the claim bypass on a request-scoped
ContextVar around the unchanged domain write, so the flip lands with the claim
check skipped AND ``os.environ`` is never mutated (the security fix). The
relay leg (applier -> call_dispatcher) is covered by
``test_done_transition_status_write_relay``.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import insert_epic_task, insert_item
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from runtime.api.test_backlog import (  # noqa: F401 - shared fixtures/helpers
    _item_field,
    _patch_externals,
    _seed_item,
    tmp_db,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.handlers import done_transition_status_writes as writes

_BYPASS_ENV_VARS = (
    "YOKE_CLAIM_BYPASS",
    "YOKE_STATUS_SOURCE",
    "YOKE_QA_GATE_BYPASS",
    "YOKE_TASK_DONE_VERIFIED",
)


@pytest.fixture(autouse=True)
def _clear_bypass_env(monkeypatch):
    for var in _BYPASS_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def full_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _item_req(function, *, item_id, payload):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id=""),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload,
    )


def _assert_env_untouched():
    for var in _BYPASS_ENV_VARS:
        assert var not in os.environ, var


class TestItemStatusSet:
    def test_bypass_flips_status_with_no_seeded_claim(self, tmp_db, monkeypatch):
        # No work_claims row is seeded: without the claim bypass the status
        # write would be denied. The request-scoped bypass makes it land.
        _seed_item(
            tmp_db, id=44, workflow_id="issue", status="implemented", project="yoke"
        )
        with _patch_externals(), monkeypatch.context() as m:
            m.setenv("YOKE_DB", tmp_db)
            for var in _BYPASS_ENV_VARS:
                m.delenv(var, raising=False)
            outcome = writes.handle_item_status_set(
                _item_req(
                    "done_transition.item_status_set",
                    item_id=44,
                    payload={
                        "field": "status",
                        "value": "release",
                        "claim_bypass": "done-transition:YOK-44",
                        "status_source": "done-transition",
                    },
                )
            )
            _assert_env_untouched()
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["applied"] is True
        assert _item_field(tmp_db, 44, "status") == "release"

    def test_missing_item_target_is_invalid(self):
        outcome = writes.handle_item_status_set(
            FunctionCallRequest(
                function="done_transition.item_status_set",
                actor=ActorContext(actor_id=None, session_id=""),
                target=TargetRef(kind="global"),
                payload={"field": "status", "value": "done"},
            )
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "target_invalid"

    def test_missing_field_is_payload_invalid(self):
        outcome = writes.handle_item_status_set(
            _item_req(
                "done_transition.item_status_set",
                item_id=44,
                payload={"value": "done"},
            )
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "payload_invalid"


class TestEpicTaskStatusSet:
    def test_bypass_and_done_verified_flip_task(self, full_db, monkeypatch):
        conn = connect_test_db(full_db)
        try:
            actor = str(seed_human_actor(conn))
            insert_item(conn, id=99, source=actor)
            insert_epic_task(
                conn, epic_id=99, task_num=1, status="reviewed-implementation"
            )
        finally:
            conn.close()

        with monkeypatch.context() as m:
            for var in _BYPASS_ENV_VARS:
                m.delenv(var, raising=False)
            outcome = writes.handle_epic_task_status_set(
                _item_req(
                    "done_transition.epic_task_status_set",
                    item_id=99,
                    payload={
                        "epic_id": "99",
                        "task_num": "1",
                        "status": "done",
                        "note": "Auto-done: epic YOK-99 marked done",
                        "claim_bypass": "done-cascade:YOK-99",
                        "task_done_verified": True,
                        "no_rebuild": True,
                        "no_github": True,
                        "no_derive": True,
                    },
                )
            )
            _assert_env_untouched()
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["rc"] == 0

        conn = connect_test_db(full_db)
        try:
            row = conn.execute(
                "SELECT status FROM epic_tasks WHERE epic_id = %s AND task_num = %s",
                (99, 1),
            ).fetchone()
        finally:
            conn.close()
        assert row[0] == "done"

    def test_missing_status_is_payload_invalid(self):
        outcome = writes.handle_epic_task_status_set(
            _item_req(
                "done_transition.epic_task_status_set",
                item_id=99,
                payload={"epic_id": "99", "task_num": "1"},
            )
        )
        assert outcome.primary_success is False
        assert outcome.error is not None
        assert outcome.error.code == "payload_invalid"
