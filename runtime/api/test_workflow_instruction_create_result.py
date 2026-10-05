"""Item creation returns its resolved execution instructions."""

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain import db_helpers
from runtime.api.item_page_reads_test_support import _connection
from runtime.api.test_workflow_execution_instruction_functions import (
    _UnclosableConnection,
    _seed_resolved_instruction,
)


def test_item_create_returns_instructions_without_a_refetch(monkeypatch):
    """A same-session creator gets the operator block in the create receipt.

    Create-and-execute-immediately flows may never re-fetch the item, so
    the create response itself must carry the resolved instructions.
    """
    conn = _UnclosableConnection(_connection())
    instruction_id = _seed_resolved_instruction(conn)
    monkeypatch.setattr(db_helpers, "connect", lambda *a, **k: conn)
    from yoke_core.domain import backlog_create_op
    from yoke_core.domain.handlers import items_create

    monkeypatch.setattr(
        backlog_create_op,
        "execute_create",
        lambda **kwargs: {"success": True, "item_id": 51, "public_ref": "R-51"},
    )
    request = FunctionCallRequest(
        function="items.create",
        actor=ActorContext(actor_id="7", session_id="session-ops"),
        target=TargetRef(kind="global"),
        payload={
            "title": "T",
            "workflow": "dash",
            "entry_surface": "cli",
            "project": "yoke",
        },
    )
    outcome = items_create.handle_item_create(request)
    assert outcome.primary_success
    resolved = outcome.result_payload["execution_instructions"]
    assert [row["id"] for row in resolved] == [instruction_id]

    # Dry-run previews create no row, so there is nothing to resolve.
    monkeypatch.setattr(
        backlog_create_op,
        "execute_create",
        lambda **kwargs: {"success": True, "item_id": 0, "dry_run": True},
    )
    preview = items_create.handle_item_create(
        request.model_copy(update={"payload": {**request.payload, "dry_run": True}})
    )
    assert preview.primary_success
    assert preview.result_payload["execution_instructions"] is None
