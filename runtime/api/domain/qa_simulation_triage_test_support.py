# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

import json

from unittest.mock import patch

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item

from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement, insert_qa_run

from runtime.api.fixtures.pg_testdb import test_database

from runtime.api.fixtures.session_holdings import insert_item_claim

from yoke_core.domain import actors

from yoke_core.domain.events_acting_identity import acting_event_identity

from yoke_core.domain.qa_obligation_settlement import settled_obligation_sql

from yoke_core.domain.qa_gate_definitions import GateTarget

from yoke_core.domain.qa_gate_summary import render_gate_summary

from yoke_core.domain.qa_gates import check_done_gate, check_verification_gate

from yoke_core.domain.qa_simulation_gate import check_epic_simulation_gate

from yoke_core.domain.qa_simulation_triage import (
    current_simulation_triage,
    record_simulation_triage,
)

from yoke_core.domain.qa_terminal_records import _blocking_requirement_rows

from yoke_core.domain.qa_obligation_settlement import item_supersession_settled

REPORT = "SIMULATION: GAPS FOUND\n- Recommendation: PROCEED\nGaps Found: 1\n### GAP #1: [WARNING] Evidence gap"


def _seed(conn, body=REPORT):
    item = insert_item(conn, id=8191, status="reviewing-implementation")
    followup = insert_item(conn, id=8192)
    requirement = insert_qa_requirement(
        conn,
        item_id=item["id"],
        qa_kind="simulation",
        qa_phase="verification",
        success_policy=json.dumps(
            {"type": "deterministic", "criteria": "result_pass", "phase": "integration"}
        ),
    )
    attempt = insert_qa_run(
        conn,
        qa_requirement_id=requirement["id"],
        qa_kind="simulation",
        verdict="fail",
        started_at="2026-10-01T00:00:00Z",
        completed_at="2026-10-01T00:00:01Z",
        raw_result=json.dumps({"body": body, "phase": "integration"}),
    )
    ref = conn.execute(
        "SELECT public_ref FROM item_refs WHERE item_id=%s", (followup["id"],)
    ).fetchone()[0]
    actor = actors.seed_canonical_human(conn, local_human_name="triage-owner")
    insert_item_claim(conn, "simulation-owner", item["id"])
    conn.commit()
    return item["id"], requirement["id"], attempt, str(ref), actor


def _record(conn, item_id, refs, **kwargs):
    return record_simulation_triage(
        conn,
        item_id,
        recommendation="PROCEED",
        rationale="Noncritical follow-up filed",
        filed_public_refs=refs,
        session_id="simulation-owner",
        **kwargs,
    )
