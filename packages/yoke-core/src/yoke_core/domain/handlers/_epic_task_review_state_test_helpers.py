"""Shared fixtures/helpers for the epic-task review + state handler tests.

Imported by ``test_workflow_item_epic_task_review.py`` and
``test_workflow_item_epic_task_state.py`` (pytest resolves fixtures
imported into a test module's namespace). Mirrors the disposable-DB
pattern of ``runtime/api/test_epic_review.py``.
"""

from __future__ import annotations

from contextlib import contextmanager
from typing import Optional
from unittest.mock import patch

import pytest

from runtime.api.conftest import insert_epic_task
from yoke_core.domain.handlers import (
    workflow_item_epic_task_review as review_handlers,
    workflow_item_epic_task_state as state_handlers,
)
from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from runtime.api.fixtures.file_test_db import (
    apply_fixture_schema_ddl,
    connect_test_db,
    init_test_db,
)

# Synthetic epic id — not a real backlog item reference.
EPIC_ID = 42

VALID_RECEIPT = """progress so far

---SUBMISSION-CHECKS-START---
test_plan: PASS
files_touched: PASS
edited_tests: SKIP (docs-only)
clean_worktree: PASS
progress_notes: PASS
file_budget: SKIP (no authored code)
---SUBMISSION-CHECKS-END---
"""

FAILING_RECEIPT = VALID_RECEIPT.replace(
    "clean_worktree: PASS", "clean_worktree: FAIL",
)


@pytest.fixture
def db(tmp_path):
    with init_test_db(tmp_path, apply_schema=apply_fixture_schema_ddl) as db_path:
        conn = connect_test_db(db_path)
        try:
            yield conn
        finally:
            conn.close()


@pytest.fixture
def db_with_task(db):
    insert_epic_task(
        db, epic_id=EPIC_ID, task_num=1, title="First task",
        status="planning", body="task body line",
    )
    return db


@pytest.fixture
def handler_conns(db_with_task):
    """Point both handler modules' ``_open_connection`` at the fixture conn."""

    @contextmanager
    def _cm():
        yield db_with_task

    with patch.object(review_handlers, "_open_connection", _cm), \
            patch.object(state_handlers, "_open_connection", _cm):
        yield db_with_task


def make_request(
    function: str,
    *,
    task_num: Optional[int] = 1,
    payload: Optional[dict] = None,
    session_id: str = "s-1",
) -> FunctionCallRequest:
    return FunctionCallRequest(
        function=function,
        actor=ActorContext(actor_id="op", session_id=session_id),
        target=TargetRef(kind="epic_task", epic_id=EPIC_ID, task_num=task_num),
        payload=payload or {},
    )


def insert_review_row(conn, req_id: int, verdict: str, body: str, ts: str) -> None:
    conn.execute(
        """INSERT INTO qa_requirements
           (id, epic_id, task_num, qa_kind, qa_phase, blocking_mode,
            requirement_source, success_policy, created_at)
           VALUES (%s, %s, 1, 'implementation_review', 'verification',
                   'blocking', 'explicit',
                   '{"type":"deterministic","criteria":"verdict_pass"}',
                   '2026-01-01T00:00:00Z')
           ON CONFLICT (id) DO NOTHING""",
        (req_id, EPIC_ID),
    )
    conn.execute(
        """INSERT INTO qa_runs
           (qa_requirement_id, executor_type, qa_kind, verdict, raw_result, created_at)
           VALUES (%s, 'agent', 'implementation_review', %s, %s, %s)""",
        (req_id, verdict, '{"body":"' + body + '"}', ts),
    )
    conn.commit()


__all__ = [
    "EPIC_ID", "VALID_RECEIPT", "FAILING_RECEIPT",
    "db", "db_with_task", "handler_conns",
    "make_request", "insert_review_row",
]
