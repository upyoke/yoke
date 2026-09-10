"""Regression coverage for the shared review-to-capture evidence resolver.

``qa_evidence_run_id`` is the one function ``item_detail_qa.py`` and
``qa_plan_detail.py`` both call to decide which run's artifacts back a
requirement's latest verdict. These guard its two failure classes: a
``human_review`` overriding an ``agent`` run that captured its own evidence
(no separate capture run to point at), and a ``capture_run_id`` reference
that does not actually belong to the requirement it is read from.
"""

from __future__ import annotations

import json

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.backlog_qa_inserts import (
    insert_qa_requirement,
    insert_qa_run,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_execution_proof import qa_evidence_run_id


def test_evidence_falls_back_to_self_capturing_agent_run_on_human_review() -> None:
    with test_database() as conn:
        insert_item(conn, id=4601, title="Self-capturing agent run")
        requirement = insert_qa_requirement(
            conn, item_id=4601, method_id="terminal-inspection"
        )
        agent_run = insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            performed_by="agent",
            verdict="undetermined",
            verdict_reason="Captured and reviewed in one step.",
            raw_result=json.dumps({"rationale": "captured and reviewed in one step"}),
        )
        conn.execute(
            "INSERT INTO qa_artifacts(qa_run_id, artifact_type, created_at) "
            "VALUES (%s, 'terminal_screenshot', %s)",
            (int(agent_run["id"]), "2026-07-29T00:00:00Z"),
        )
        conn.commit()
        human_review = insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            performed_by="human_review",
            verdict="pass",
            raw_result=json.dumps({}),
        )

        resolved = qa_evidence_run_id(
            conn,
            requirement_id=int(requirement["id"]),
            run_id=int(human_review["id"]),
            performed_by="human_review",
            raw_result=human_review["raw_result"],
        )

        assert resolved == int(agent_run["id"])


def test_evidence_rejects_capture_reference_from_another_requirement() -> None:
    with test_database() as conn:
        insert_item(conn, id=4602, title="Mismatched capture reference")
        own_requirement = insert_qa_requirement(conn, item_id=4602)
        other_requirement = insert_qa_requirement(conn, item_id=4602)
        foreign_run = insert_qa_run(
            conn,
            qa_requirement_id=int(other_requirement["id"]),
            performed_by="host_control",
            verdict="pass",
        )
        review_run = insert_qa_run(
            conn,
            qa_requirement_id=int(own_requirement["id"]),
            performed_by="agent",
            verdict="pass",
            raw_result=json.dumps({"capture_run_id": int(foreign_run["id"])}),
        )

        resolved = qa_evidence_run_id(
            conn,
            requirement_id=int(own_requirement["id"]),
            run_id=int(review_run["id"]),
            performed_by="agent",
            raw_result=review_run["raw_result"],
        )

        assert resolved == int(review_run["id"])


def test_evidence_rejects_a_capture_reference_that_does_not_exist() -> None:
    with test_database() as conn:
        insert_item(conn, id=4603, title="Dangling capture reference")
        requirement = insert_qa_requirement(conn, item_id=4603)
        review_run = insert_qa_run(
            conn,
            qa_requirement_id=int(requirement["id"]),
            performed_by="agent",
            verdict="pass",
            raw_result=json.dumps({"capture_run_id": 999999999}),
        )

        resolved = qa_evidence_run_id(
            conn,
            requirement_id=int(requirement["id"]),
            run_id=int(review_run["id"]),
            performed_by="agent",
            raw_result=review_run["raw_result"],
        )

        assert resolved == int(review_run["id"])
