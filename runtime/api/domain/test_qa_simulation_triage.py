"""Bounded triage retains failed evidence and cannot rescue a newer attempt."""

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
    _system, actor = actors.seed_canonical_actors(conn, local_human_name="triage-owner")
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


class _BorrowedConnection:
    def __init__(self, conn):
        self.conn = conn

    def __getattr__(self, name):
        return getattr(self.conn, name)

    def close(self):
        pass


@pytest.mark.parametrize("next_verdict", [None, "fail"])
def test_triage_is_exact_attempt_discharge_without_passing_run(next_verdict):
    with test_database() as conn:
        item_id, requirement_id, attempt, ref, actor = _seed(conn)
        before = tuple(
            conn.execute(
                "SELECT started_at,raw_result,verdict,verdict_reason FROM qa_runs WHERE id=%s",
                (attempt["id"],),
            ).fetchone()
        )
        with acting_event_identity(session_id="simulation-owner", actor_id=actor):
            receipt = _record(conn, item_id, [ref])
            replay = _record(conn, item_id, [ref])
        assert receipt == replay
        assert receipt["run_id"] == receipt["capture_run_id"] == attempt["id"]
        assert receipt["actor_id"] == actor
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id=%s",
                (requirement_id,),
            ).fetchone()[0]
            == 1
        )
        assert (
            tuple(
                conn.execute(
                    "SELECT started_at,raw_result,verdict,verdict_reason FROM qa_runs WHERE id=%s",
                    (attempt["id"],),
                ).fetchone()
            )
            == before
        )
        assert conn.execute(
            f"SELECT {settled_obligation_sql(conn, 'q')} FROM qa_requirements q WHERE id=%s",
            (requirement_id,),
        ).fetchone()[0]
        assert item_supersession_settled(_blocking_requirement_rows(conn, item_id)[0])
        with patch(
            "yoke_core.domain.qa_simulation_gate.connect",
            return_value=_BorrowedConnection(conn),
        ):
            assert check_epic_simulation_gate(item_id, "test").passed
        insert_qa_run(
            conn,
            qa_requirement_id=requirement_id,
            qa_kind="simulation",
            verdict=next_verdict,
            started_at="2026-10-01T00:00:02Z",
            raw_result="{}",
        )
        assert current_simulation_triage(conn, requirement_id) is None
        assert not item_supersession_settled(
            _blocking_requirement_rows(conn, item_id)[0]
        )
        with patch(
            "yoke_core.domain.qa_simulation_gate.connect",
            return_value=_BorrowedConnection(conn),
        ):
            assert not check_epic_simulation_gate(item_id, "test").passed
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_name='QaSimulationTriaged'"
            ).fetchone()[0]
            == 1
        )


@pytest.mark.parametrize(
    "body,refs,reason",
    [
        (REPORT.replace("WARNING", "CRITICAL"), True, "not_authorized"),
        (REPORT.replace("PROCEED", "FIX_FIRST"), True, "not_authorized"),
        (REPORT.replace("- Recommendation: PROCEED", ""), True, "not_authorized"),
        (REPORT, False, "followups_missing"),
    ],
)
def test_triage_validates_retained_report_and_followups(body, refs, reason):
    with test_database() as conn:
        item_id, requirement_id, _attempt, ref, actor = _seed(conn, body)
        with acting_event_identity(session_id="simulation-owner", actor_id=actor):
            with pytest.raises(ValueError, match=f"simulation_triage_{reason}"):
                _record(conn, item_id, [ref] if refs else [])
        assert current_simulation_triage(conn, requirement_id) is None
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM events WHERE event_name='QaSimulationTriaged'"
            ).fetchone()[0]
            == 0
        )


def test_conflicting_triage_replay_and_unknown_followup_refuse():
    with test_database() as conn:
        item_id, requirement_id, _attempt, ref, actor = _seed(conn)
        with acting_event_identity(session_id="simulation-owner", actor_id=actor):
            with pytest.raises(ValueError, match="followups_invalid"):
                _record(conn, item_id, ["YOK-99999999"])
            receipt = _record(conn, item_id, [ref])
            with pytest.raises(ValueError, match="replay_conflict"):
                record_simulation_triage(
                    conn,
                    item_id,
                    recommendation="PROCEED",
                    rationale="Different adjudication",
                    filed_public_refs=[ref],
                    session_id="simulation-owner",
                )
        assert current_simulation_triage(conn, requirement_id) == receipt


def test_discharge_survives_missing_telemetry():
    with test_database() as conn:
        item_id, requirement_id, _attempt, ref, actor = _seed(conn)
        with (
            acting_event_identity(session_id="simulation-owner", actor_id=actor),
            patch(
                "yoke_core.domain.qa_events.emit_qa_requirement_event",
                return_value=None,
            ),
        ):
            receipt = _record(conn, item_id, [ref])
        conn.execute("DELETE FROM events WHERE event_name='QaSimulationTriaged'")
        conn.commit()
        assert current_simulation_triage(conn, requirement_id) == receipt
        assert conn.execute(
            f"SELECT {settled_obligation_sql(conn, 'q')} FROM qa_requirements q WHERE id=%s",
            (requirement_id,),
        ).fetchone()[0]
