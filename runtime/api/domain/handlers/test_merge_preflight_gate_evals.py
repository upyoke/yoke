"""In-process integration coverage for the merge preflight gate reads.

Exercises the three ``merge.preflight.*`` internal handlers against a seeded
Postgres authority. Each handler is a thin wrapper over unchanged read state;
these tests prove the wrapper reads real DB rows server-side and returns the
verdict in its declared response shape for both the empty/clear case and the
populated/block case. This is the local / in-process leg of the ALL-MODES
contract; the relay leg is covered by
``test_merge_worktree_prepare_transport``.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.fixtures.backlog_inserts import (
    insert_epic_task,
    insert_item,
    insert_item_worktree,
)
from runtime.api.fixtures.file_test_db import connect_test_db, init_test_db
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.actors import seed_human_actor
from yoke_core.domain.db_helpers import iso8601_now
from yoke_core.domain.handlers import merge_preflight_gate_evals as gates


@pytest.fixture
def db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with init_test_db(tmp_path) as db_path:
        monkeypatch.setenv("YOKE_DB", db_path)
        yield db_path


def _item_envelope(function, *, item_id, payload=None):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-merge-preflight"),
        target=TargetRef(kind="item", item_id=item_id),
        payload=payload or {},
    )


def _global_envelope(function, *, payload):
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id=None, session_id="s-merge-preflight"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _ensure_dependency_schema(conn) -> None:
    """The dependency table is shepherd-owned, not part of core cmd_init."""
    from yoke_core.domain import shepherd_init

    shepherd_init.cmd_init(conn)


def _insert_dep(conn, *, dependent: int, blocking: int, satisfaction: str) -> None:
    conn.execute(
        "INSERT INTO item_dependencies "
        "(dependent_item, blocking_item, gate_point, satisfaction, source, "
        "created_at) VALUES (%s, %s, 'integration', %s, 'test', %s)",
        (f"YOK-{dependent}", f"YOK-{blocking}", satisfaction, iso8601_now()),
    )
    conn.commit()


class TestEpicTaskStatuses:
    def test_reports_every_task_in_task_num_order(self, db):
        epic_id = 9301
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=epic_id, source=str(seed_human_actor(conn)))
            insert_epic_task(conn, epic_id=epic_id, task_num=2, status="implementing")
            insert_epic_task(conn, epic_id=epic_id, task_num=1, status="done")
        finally:
            conn.close()
        outcome = gates.handle_epic_task_statuses(
            _item_envelope("merge.preflight.epic_task_statuses", item_id=epic_id)
        )
        assert outcome.primary_success, outcome.error
        tasks = outcome.result_payload["tasks"]
        assert [t["task_num"] for t in tasks] == [1, 2]
        assert [t["status"] for t in tasks] == ["done", "implementing"]
        gates.EpicTaskStatusesResponse(**outcome.result_payload)

    def test_empty_when_no_tasks(self, db):
        epic_id = 9302
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=epic_id, source=str(seed_human_actor(conn)))
        finally:
            conn.close()
        outcome = gates.handle_epic_task_statuses(
            _item_envelope("merge.preflight.epic_task_statuses", item_id=epic_id)
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["tasks"] == []


class TestDependencyGate:
    def test_clear_when_no_dependencies(self, db):
        item_id = 9311
        conn = connect_test_db(db)
        try:
            _ensure_dependency_schema(conn)
            insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
        finally:
            conn.close()
        outcome = gates.handle_dependency_gate(
            _global_envelope(
                "merge.preflight.dependency_gate",
                payload={"item_ref": f"YOK-{item_id}", "gate_point": "integration"},
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["is_blocked"] is False
        assert outcome.result_payload["unsatisfied_blockers"] == []
        gates.DependencyGateResponse(**outcome.result_payload)

    def test_blocked_on_unsatisfied_integration_dependency(self, db):
        dependent, blocking = 9312, 9320
        conn = connect_test_db(db)
        try:
            _ensure_dependency_schema(conn)
            actor = seed_human_actor(conn)
            insert_item(conn, id=dependent, source=str(actor))
            insert_item(conn, id=blocking, status="implementing", source=str(actor))
            _insert_dep(
                conn, dependent=dependent, blocking=blocking,
                satisfaction="status:done",
            )
        finally:
            conn.close()
        outcome = gates.handle_dependency_gate(
            _global_envelope(
                "merge.preflight.dependency_gate",
                payload={"item_ref": f"YOK-{dependent}", "gate_point": "integration"},
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["is_blocked"] is True
        blockers = outcome.result_payload["unsatisfied_blockers"]
        assert len(blockers) == 1
        assert blockers[0]["blocking_item"] == f"YOK-{blocking}"


class TestBlockedGate:
    def test_not_applicable_without_active_worktree(self, db):
        item_id = 9331
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
        finally:
            conn.close()
        outcome = gates.handle_blocked_gate(
            _global_envelope(
                "merge.preflight.blocked_gate", payload={"branch": f"YOK-{item_id}"}
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload == {"applicable": False}

    def test_not_blocked_when_flag_clear(self, db):
        item_id = 9332
        conn = connect_test_db(db)
        try:
            insert_item(conn, id=item_id, source=str(seed_human_actor(conn)))
            insert_item_worktree(
                conn, item_id=item_id, branch=f"YOK-{item_id}", lane_role="worker"
            )
        finally:
            conn.close()
        outcome = gates.handle_blocked_gate(
            _global_envelope(
                "merge.preflight.blocked_gate", payload={"branch": f"YOK-{item_id}"}
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["applicable"] is True
        assert outcome.result_payload["item_id"] == item_id
        assert outcome.result_payload["blocked"] is False
        gates.BlockedGateResponse(**outcome.result_payload)

    def test_blocked_reports_reason(self, db):
        item_id = 9333
        conn = connect_test_db(db)
        try:
            insert_item(
                conn, id=item_id, source=str(seed_human_actor(conn)),
                blocked=1, blocked_reason="upstream unresolved",
            )
            insert_item_worktree(
                conn, item_id=item_id, branch=f"YOK-{item_id}", lane_role="worker"
            )
        finally:
            conn.close()
        outcome = gates.handle_blocked_gate(
            _global_envelope(
                "merge.preflight.blocked_gate", payload={"branch": f"YOK-{item_id}"}
            )
        )
        assert outcome.primary_success, outcome.error
        assert outcome.result_payload["applicable"] is True
        assert outcome.result_payload["blocked"] is True
        assert outcome.result_payload["reason"] == "upstream unresolved"
