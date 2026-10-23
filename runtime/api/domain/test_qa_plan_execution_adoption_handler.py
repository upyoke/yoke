"""The registered adoption boundary retains audit and refusal authority."""

from psycopg.errors import LockNotAvailable

from runtime.api.domain.test_qa_plan_execution_adoption import _setup
from runtime.api.fixtures.pg_testdb import test_database
from yoke_contracts.api.function_call import FunctionCallRequest
from yoke_core.domain.handlers import qa_plan_execution_adoption as handler


def _request(execution_id, actor):
    return FunctionCallRequest(
        function="qa.plan_execution.adopt",
        request_id="adopt-request",
        actor={"actor_id": actor, "session_id": "successor-session"},
        target={"kind": "item", "item_id": 4901},
        payload={"execution_id": execution_id, "reason": "Restaffed QA"},
    )


def test_registered_handler_adopts_with_durable_receipt(monkeypatch):
    from yoke_core.domain import db_helpers, yoke_function_registry
    from yoke_core.domain.handlers.__init_register__ import register_all_handlers

    register_all_handlers()
    entry = yoke_function_registry.lookup("qa.plan_execution.adopt")
    assert entry is not None
    assert entry.minimum_serving_version == "next-release"
    assert entry.claim_required_kind == "qa_subject"
    assert entry.ambient_session_required
    with test_database() as conn:
        execution, _, _, actor = _setup(conn)

        class BorrowedConnection:
            def __getattr__(self, name):
                return getattr(conn, name)

            def close(self):
                pass

        monkeypatch.setattr(db_helpers, "connect", BorrowedConnection)
        outcome = entry.handler(_request(execution["id"], actor))
        assert outcome.primary_success
        assert outcome.result_payload["state"] == "adopted"
        assert conn.execute(
            "SELECT previous_session_id,session_id FROM qa_plan_execution_adoptions"
        ).fetchone() == (execution["session_id"], "successor-session")


def test_busy_adoption_rolls_back_and_teaches_retry(monkeypatch):
    from yoke_core.domain import (
        db_helpers,
        qa_plan_execution_store,
        qa_plan_execution_reentry,
    )

    calls = []

    class Connection:
        def rollback(self):
            calls.append("rollback")

        def close(self):
            calls.append("close")

    def busy(*_, **__):
        raise LockNotAvailable("busy")

    monkeypatch.setattr(db_helpers, "connect", Connection)
    monkeypatch.setattr(
        qa_plan_execution_reentry, "bound_checkin_queries", lambda _: None
    )
    monkeypatch.setattr(qa_plan_execution_store, "lock_plan_execution", busy)
    outcome = handler.handle_execution_adopt(_request("capture", "7"))
    assert not outcome.primary_success
    assert outcome.error.code == "qa_adoption_busy"
    assert "retry the same adoption" in outcome.error.message
    assert calls == ["rollback", "close"]
