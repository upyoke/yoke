# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

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


def _seed_resolved_instruction(conn) -> int:
    from yoke_core.domain import workflow_execution_instructions as domain

    instruction_id = domain.create_instruction(
        conn,
        content="Run the QA gate.",
    )
    domain.set_instruction_scope(
        conn,
        instruction_id,
        workflow_ids=["dash"],
        applies_to_all_projects=True,
        project_ids=[],
    )
    conn.commit()
    return instruction_id
