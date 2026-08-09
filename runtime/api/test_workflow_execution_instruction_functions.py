"""Handler contract for the workflow.execution_instruction function family."""

from __future__ import annotations

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers
from yoke_core.domain.handlers import (
    item_page_reads,
    reads,
    workflow_execution_instructions_crud as crud,
)
from runtime.api.item_page_reads_test_support import _connection


class _UnclosableConnection:
    """Share one in-memory fixture across readers that close their conn."""

    def __init__(self, conn):
        self._conn = conn

    def close(self) -> None:
        pass

    def __enter__(self):
        self._conn.__enter__()
        return self

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def _request(function: str, payload: dict) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="7", session_id="session-ops"),
        target=TargetRef(kind="global"),
        payload=payload,
    )


def _capture_events(monkeypatch) -> list:
    emitted = []
    monkeypatch.setattr(
        crud._events,
        "emit_event",
        lambda name, **kwargs: emitted.append((name, kwargs)),
    )
    return emitted


def test_registrations_expose_the_crud_contract() -> None:
    by_id = {entry["function_id"]: entry for entry in crud.REGISTRATIONS}
    assert set(by_id) == {
        "workflow.execution_instruction.create",
        "workflow.execution_instruction.update",
        "workflow.execution_instruction.set_scope",
        "workflow.execution_instruction.list",
        "workflow.execution_instruction.delete",
    }
    assert by_id["workflow.execution_instruction.list"]["side_effects"] == []
    create = by_id["workflow.execution_instruction.create"]
    assert create["side_effects"] == ["db_write", "event_emit"]
    assert create["emitted_event_names"] == [crud.INSTRUCTION_CREATED_EVENT]
    assert create["target_kinds"] == ["global"]


def test_crud_handlers_write_rows_and_emit_audited_events(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(db_helpers, "connect", lambda *a, **k: conn)
    emitted = _capture_events(monkeypatch)

    created = crud.handle_instruction_create(_request(
        "workflow.execution_instruction.create",
        {"content": "Run doctor first."},
    ))
    assert created.primary_success
    instruction_id = created.result_payload["instruction_id"]

    scoped = crud.handle_instruction_set_scope(_request(
        "workflow.execution_instruction.set_scope",
        {
            "instruction_id": instruction_id,
            "workflow_ids": ["dash"],
            "applies_to_all_projects": True,
            "project_ids": [],
        },
    ))
    assert scoped.primary_success

    listed = crud.handle_instruction_list(_request(
        "workflow.execution_instruction.list", {},
    ))
    rows = listed.result_payload["instructions"]
    assert [row["workflow_ids"] for row in rows] == [["dash"]]
    assert rows[0]["applies_to_all_projects"] is True
    assert rows[0]["applies_to_all_workflows"] is False

    updated = crud.handle_instruction_update(_request(
        "workflow.execution_instruction.update",
        {"instruction_id": instruction_id, "content": "Rewritten."},
    ))
    assert updated.primary_success

    deleted = crud.handle_instruction_delete(_request(
        "workflow.execution_instruction.delete",
        {"instruction_id": instruction_id},
    ))
    assert deleted.primary_success

    names = [name for name, _ in emitted]
    assert names == [
        crud.INSTRUCTION_CREATED_EVENT,
        crud.INSTRUCTION_SCOPE_SET_EVENT,
        crud.INSTRUCTION_UPDATED_EVENT,
        crud.INSTRUCTION_DELETED_EVENT,
    ]
    assert all(kwargs["context"]["actor_id"] == 7 for _, kwargs in emitted)
    assert all(
        kwargs["session_id"] == "session-ops" for _, kwargs in emitted
    )


def test_missing_instruction_and_empty_content_fail_closed(monkeypatch):
    conn = _connection()
    monkeypatch.setattr(db_helpers, "connect", lambda *a, **k: conn)
    _capture_events(monkeypatch)

    missing = crud.handle_instruction_delete(_request(
        "workflow.execution_instruction.delete", {"instruction_id": 404},
    ))
    assert not missing.primary_success
    assert missing.error.code == "not_found"

    blank = crud.handle_instruction_create(_request(
        "workflow.execution_instruction.create",
        {"content": "   "},
    ))
    assert not blank.primary_success
    assert blank.error.code == "empty_content_refused"


def _seed_resolved_instruction(conn) -> int:
    from yoke_core.domain import workflow_execution_instructions as domain

    instruction_id = domain.create_instruction(
        conn, content="Run the QA gate.",
    )
    domain.set_instruction_scope(
        conn, instruction_id, workflow_ids=["dash"],
        applies_to_all_projects=True, project_ids=[],
    )
    conn.commit()
    return instruction_id


def test_item_detail_returns_instructions_as_a_separate_field(monkeypatch):
    conn = _UnclosableConnection(_connection())
    instruction_id = _seed_resolved_instruction(conn)
    monkeypatch.setattr(db_helpers, "connect", lambda *a, **k: conn)

    request = FunctionCallRequest(
        function="items.detail.get",
        actor=ActorContext(actor_id="7", session_id="session-ops"),
        target=TargetRef(kind="item", item_id=51),
        payload={},
    )
    outcome = item_page_reads.handle_item_detail_get(request)

    assert outcome.primary_success
    resolved = outcome.result_payload["execution_instructions"]
    assert [row["id"] for row in resolved] == [instruction_id]
    # The item read model itself stays untouched — the block is a sibling
    # field, so structured-field writes can never round-trip it back.
    assert "execution_instructions" not in outcome.result_payload["item"]


def test_items_get_attaches_instructions_only_for_body_reads(monkeypatch):
    conn = _connection()
    instruction_id = _seed_resolved_instruction(conn)
    monkeypatch.setattr(db_helpers, "connect", lambda *a, **k: conn)
    from yoke_core.domain import items_queries

    monkeypatch.setattr(
        items_queries, "query_item", lambda item_id, col: f"<{col}>",
    )

    body_request = FunctionCallRequest(
        function="items.get.run",
        actor=ActorContext(actor_id="7", session_id="session-ops"),
        target=TargetRef(kind="item", item_id=51),
        payload={"fields": ["body"]},
    )
    outcome = reads.handle_items_get(body_request)
    assert outcome.primary_success
    resolved = outcome.result_payload["execution_instructions"]
    assert [row["id"] for row in resolved] == [instruction_id]

    status_request = body_request.model_copy(
        update={"payload": {"fields": ["status"]}}
    )
    status_outcome = reads.handle_items_get(status_request)
    assert status_outcome.primary_success
    assert "execution_instructions" not in status_outcome.result_payload
