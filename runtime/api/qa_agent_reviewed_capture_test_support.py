"""Seed one agent-reviewed Browser case the way its real producers do.

A capture is recorded through ``qa.run.add`` / ``qa.run.complete`` and read
back through the real release gate, so the tests that share these helpers
exercise producer and gate against each other rather than against a
restatement of either.
"""

from __future__ import annotations

import json
from unittest.mock import patch

from yoke_contracts.api.function_call import (
    ActorContext,
    FunctionCallRequest,
    TargetRef,
)
from yoke_core.domain.handlers import qa_browser_writes
from yoke_core.domain.qa_browser_evidence_check import (
    check_browser_evidence_present,
)

from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement

ITEM_ID = 8301
NOW = "2026-09-17T00:00:00Z"


def request(function_id: str, requirement_id: int, payload: dict):
    return FunctionCallRequest(
        function=function_id,
        actor=ActorContext(actor_id="op", session_id="s-1"),
        target=TargetRef(kind="qa_requirement", qa_requirement_id=requirement_id),
        payload=payload,
    )


def seed_case(conn, *, requirement_id: int, method_id: str, verdict_path: str):
    insert_item(conn, id=ITEM_ID, title="Reviewed by an agent")
    insert_qa_requirement(
        conn,
        id=requirement_id,
        item_id=ITEM_ID,
        qa_kind="method_case",
        qa_phase="verification",
        blocking_mode="blocking",
        method_id=method_id,
        method_name="Browser inspection",
        runner_id="browser_substrate",
        verdict_path=verdict_path,
        success_policy="",
    )
    conn.commit()


def capture(conn, requirement_id: int) -> int:
    """Record a capture exactly as the browser substrate does."""
    with patch("yoke_core.domain.qa_events.emit_qa_run_event"):
        added = qa_browser_writes.handle_qa_run_add(
            request("qa.run.add", requirement_id, {"performed_by": "browser_substrate"})
        )
        assert added.primary_success, added.error
        run_id = int(added.result_payload["qa_run_id"])
        conn.execute(
            "INSERT INTO qa_artifacts (qa_run_id, artifact_type, content_type, "
            "artifact_handle, created_at) VALUES (%s, 'browser_screenshot', "
            "'image/png', %s, %s)",
            (
                run_id,
                json.dumps({"backend": "local", "path": "/tmp/shot.png"}),
                NOW,
            ),
        )
        conn.commit()
        completed = qa_browser_writes.handle_qa_run_complete(
            request(
                "qa.run.complete",
                requirement_id,
                {"run_id": run_id, "execution_status": "captured"},
            )
        )
        assert completed.primary_success, completed.error
    return run_id


def capture_outcome(conn, run_id: int):
    row = conn.execute(
        "SELECT execution_status, case_outcome, verdict FROM qa_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    return row["execution_status"], row["case_outcome"], row["verdict"]


def browser_evidence_gate(conn):
    return check_browser_evidence_present(
        conn,
        where="r.item_id = %s",
        params=(ITEM_ID,),
        name="browser-evidence",
        transition_name="done",
    )


__all__ = [
    "ITEM_ID",
    "NOW",
    "browser_evidence_gate",
    "capture",
    "capture_outcome",
    "request",
    "seed_case",
]
