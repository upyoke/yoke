# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import pytest

from pydantic import ValidationError

from yoke_core.domain import workflow_execution_instructions as domain

from yoke_core.domain import db_helpers

from yoke_core.domain.execution_instruction_delivery import InstructionDelivery

from yoke_core.domain.handlers import (
    workflow_execution_instructions_crud as crud,
    reads,
    lifecycle_transition,
)

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)

from runtime.api.item_page_reads_test_support import _connection

from runtime.api.workflow_execution_instruction_functions_test_support import (
    _UnclosableConnection,
    _request,
    _capture_events,
)


@pytest.fixture
def conn(monkeypatch):
    connection = _UnclosableConnection(_connection())
    monkeypatch.setattr(db_helpers, "connect", lambda *a, **k: connection)
    _capture_events(monkeypatch)
    return connection


def seed(conn, content, **delivery):
    identifier = domain.create_instruction(conn, content=content, delivery=delivery)
    domain.set_instruction_scope(
        conn,
        identifier,
        workflow_ids=["dash"],
        applies_to_all_projects=True,
        project_ids=[],
    )
    conn.commit()
    return identifier
