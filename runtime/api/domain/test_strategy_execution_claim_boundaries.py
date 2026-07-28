"""Boundary coverage for Blitz execution-document claims and closeout."""

from __future__ import annotations

from pathlib import Path

import pytest

from runtime.api.domain.strategy_execution_test_support import (
    seed_blitz_item,
    seed_session_claim,
    seed_strategy_doc,
    strategy_test_database,
)
from runtime.api.fixtures.file_test_db import connect_test_db
from yoke_core.domain.strategy_coordination import blitz_completion_evidence
from yoke_core.domain.strategy_execution import (
    acquire_strategy_doc_claim,
    link_execution_document,
)
from yoke_core.domain.workflow_item_binding_validation import (
    WorkflowItemBindingError,
)


@pytest.fixture
def tmp_db(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    with strategy_test_database(tmp_path, monkeypatch) as db_path:
        yield db_path


def test_terminal_blitz_cannot_acquire_document_claim(tmp_db: str) -> None:
    conn = connect_test_db(tmp_db)
    try:
        seed_strategy_doc(conn, "TERMINAL-PLAN", "# Terminal plan\n")
        seed_blitz_item(conn, 2003, 2003)
        seed_session_claim(conn, 2003, "session-terminal")
        link_execution_document(
            conn,
            item_id=2003,
            project_id=1,
            slug="TERMINAL-PLAN",
            actor_id=1,
            session_id="session-terminal",
        )
        conn.execute("UPDATE items SET status='cancelled' WHERE id=2003")
        conn.commit()

        with pytest.raises(WorkflowItemBindingError, match="terminal"):
            acquire_strategy_doc_claim(
                conn,
                item_id=2003,
                session_id="session-terminal",
                actor_id=1,
            )
    finally:
        conn.close()


def test_blitz_completion_rejects_planning_prose_with_closeout_keywords(
    tmp_db: str,
) -> None:
    conn = connect_test_db(tmp_db)
    try:
        seed_strategy_doc(
            conn,
            "PLANNING-PROSE",
            "# Plan\n\nThe planned completion includes verification evidence. "
            "Remaining work will be reconciled with the parent.\n",
        )
        seed_blitz_item(conn, 2002, 2002)
        link_execution_document(
            conn,
            item_id=2002,
            project_id=1,
            slug="PLANNING-PROSE",
            actor_id=1,
            session_id="session-a",
        )
        evidence = blitz_completion_evidence(conn, 2002)
    finally:
        conn.close()

    assert evidence["satisfied"] is False
    assert set(evidence["missing"]) == {
        "completion",
        "changes",
        "remaining_work",
        "verification",
        "parent_reconciliation",
    }
