"""Simulation identity validation and exact-attempt receipts."""

import json
from contextlib import contextmanager
from unittest.mock import patch

import pytest

from runtime.api.conftest import insert_item
from runtime.api.test_epic_review import db as db
from yoke_core.domain import epic
from yoke_core.domain.handlers import workflow_item_epic_task_state as handlers
from yoke_core.domain.project_identity import render_item_ref
from yoke_core.domain.simulation_report_headers import (
    SimulationReportError,
    parse_simulation_headers,
)
from yoke_core.domain.simulation_attempt_read import SimulationReadbackError
from runtime.api.domain.handlers._epic_task_review_state_test_helpers import (
    make_request,
)

ITEM_ID = 42
SEQUENCE = 109


def report(ref, verdict="CLEAN"):
    return f"SIMULATION: {verdict}\nEPIC: {ref}"


@pytest.mark.parametrize(
    "body,code",
    [
        ("", "simulation_identity_missing"),
        ("notes\nSIMULATION: CLEAN\nEPIC: {ref}", "simulation_identity_missing"),
        ("SIMULATION: CLEAN", "simulation_identity_missing"),
        ("SIMULATION: MAYBE\nEPIC: {ref}", "simulation_verdict_invalid"),
        ("SIMULATION: CLEAN extra\nEPIC: {ref}", "simulation_verdict_invalid"),
        ("SIMULATION: CLEAN\nEPIC: WRONG-12", "simulation_identity_mismatch"),
        (
            "SIMULATION: CLEAN\nEPIC: {ref}\nSIMULATION: GAPS FOUND",
            "simulation_verdict_invalid",
        ),
        (
            "SIMULATION: CLEAN\nEPIC: {ref}\nEPIC: WRONG-12",
            "simulation_identity_mismatch",
        ),
    ],
)
def test_invalid_headers_are_diagnosed(body, code):
    ref = f"TST-{SEQUENCE}"
    with pytest.raises(SimulationReportError) as exc:
        parse_simulation_headers(body.format(ref=ref), ref)
    assert exc.value.code == code
    assert f"EPIC: {ref}" in str(exc.value)
    assert "SIMULATION: CLEAN or SIMULATION: GAPS FOUND" in str(exc.value)


@pytest.mark.parametrize("verdict", ["CLEAN", "GAPS FOUND"])
def test_repeated_headers_and_quoted_examples_are_content(verdict):
    ref = f"TST-{SEQUENCE}"
    body = (
        report(ref, verdict)
        + "\n\n"
        + report(ref, verdict)
        + """
```markdown
SIMULATION: MAYBE
EPIC: WRONG-12
```
~~~~
EPIC: WRONG-12
~~~
SIMULATION: MAYBE
~~~~
> EPIC: WRONG-12
> SIMULATION: MAYBE
"""
    )
    assert parse_simulation_headers(body, ref) == verdict
    assert epic._parse_simulation_result(body) == verdict


@pytest.mark.parametrize(
    "body", ["## Result: CLEAN", "**Result:** 3 gaps found", "SIMULATION: CLEAN"]
)
def test_verdict_parser_rejects_noncanonical_reports(body):
    assert epic._parse_simulation_result(body) is None


@pytest.fixture(params=["TST", "ALT"])
def item(db, request):
    row = insert_item(
        db, id=ITEM_ID, project_sequence=SEQUENCE, workflow_id="epic", status="planning"
    )
    db.execute(
        "UPDATE projects SET public_item_prefix = %s WHERE id = %s",
        (request.param, row["project_id"]),
    )
    db.commit()
    return render_item_ref(db, ITEM_ID)


@contextmanager
def writes(db, *, concurrent=False):
    def add_req(**kwargs):
        row = db.execute(
            """INSERT INTO qa_requirements
            (item_id, qa_kind, qa_phase, blocking_mode, requirement_source, success_policy, created_at)
            VALUES (%s, 'simulation', 'verification', 'blocking', 'explicit', %s, '2026-01-01T00:00:00Z') RETURNING id""",
            (kwargs["item_id"], kwargs["success_policy"]),
        ).fetchone()
        db.commit()
        return row[0]

    def add_run(**kwargs):
        row = db.execute(
            """INSERT INTO qa_runs
            (qa_requirement_id, performed_by, qa_kind, verdict, raw_result, created_at)
            VALUES (%s, 'agent', 'simulation', %s, %s, '2026-01-01T00:00:00Z') RETURNING id""",
            (kwargs["requirement_id"], kwargs["verdict"], kwargs["raw_result"]),
        ).fetchone()
        if concurrent:
            db.execute(
                """INSERT INTO qa_runs
                (qa_requirement_id, performed_by, qa_kind, verdict, raw_result, created_at)
                VALUES (%s, 'agent', 'simulation', 'fail', %s, '2026-01-02T00:00:00Z')""",
                (kwargs["requirement_id"], kwargs["raw_result"]),
            )
        db.commit()
        return row[0]

    with (
        patch.object(epic, "_qa_requirement_add_silent", side_effect=add_req) as req,
        patch.object(epic, "_qa_run_add_silent", side_effect=add_run) as run,
    ):
        yield req, run


def invoke(db, body):
    @contextmanager
    def connection():
        yield db

    with patch.object(handlers, "_open_connection", connection):
        return handlers.handle_simulation_upsert(
            make_request(
                "workflow_item.epic_task.simulation_upsert",
                task_num=None,
                payload={"phase": "plan", "body": body},
            )
        )


@pytest.mark.parametrize(
    "body,code",
    [
        ("SIMULATION: CLEAN", "simulation_identity_missing"),
        ("SIMULATION: CLEAN\nEPIC: {wrong}", "simulation_identity_mismatch"),
        ("{report}\nEPIC: {wrong}", "simulation_identity_mismatch"),
        ("{report}\nSIMULATION: GAPS FOUND", "simulation_verdict_invalid"),
        ("SIMULATION: INVALID\nEPIC: {ref}", "simulation_verdict_invalid"),
    ],
)
def test_handler_refuses_before_any_write_for_public_sequences(db, item, body, code):
    wrong = item.rsplit("-", 1)[0] + f"-{ITEM_ID}"
    with writes(db) as (req, run):
        outcome = invoke(db, body.format(report=report(item), wrong=wrong, ref=item))
    assert not outcome.primary_success
    assert outcome.error.code == code
    assert item in outcome.error.message
    req.assert_not_called()
    run.assert_not_called()


def test_receipt_credits_own_run_and_retains_attempts(db, item):
    with writes(db, concurrent=True) as (req, run):
        first = invoke(db, report(item))
        second = invoke(db, report(item, "GAPS FOUND"))
    assert first.primary_success and second.primary_success
    receipt = first.result_payload
    assert receipt["public_ref"] == item
    assert receipt["verdict"] == "CLEAN" and receipt["verified"] is True
    assert receipt["run_id"] != second.result_payload["run_id"]
    assert receipt["requirement_id"] == second.result_payload["requirement_id"]
    assert "body" not in receipt
    assert (
        db.execute(
            "SELECT COUNT(*) FROM qa_runs WHERE qa_requirement_id = %s",
            (receipt["requirement_id"],),
        ).fetchone()[0]
        == 4
    )
    req.assert_called_once()
    assert run.call_count == 2


@pytest.mark.parametrize(
    "damage",
    ["missing", "subject", "phase", "verdict", "requirement", "kind", "policy"],
)
def test_readback_failure_returns_known_ids_without_rewriting(db, item, damage):
    from yoke_core.domain import simulation_attempt_read

    original = simulation_attempt_read.query_one

    def corrupt(*args):
        row = original(*args)
        if damage == "missing":
            return None
        row = dict(row)
        if damage == "subject":
            row["item_id"] = ITEM_ID + 1
        elif damage == "phase":
            row["raw_result"] = json.dumps({"phase": "other"})
        elif damage == "verdict":
            row["verdict"] = "fail"
        elif damage == "requirement":
            row["qa_requirement_id"] += 1
        elif damage == "kind":
            row["run_kind"] = "command"
        elif damage == "policy":
            row["success_policy"] = "invalid json"
        return row

    with (
        writes(db) as (req, run),
        patch.object(simulation_attempt_read, "query_one", side_effect=corrupt),
    ):
        outcome = invoke(db, report(item))
    assert not outcome.primary_success
    assert outcome.error.code == SimulationReadbackError.code
    assert outcome.result_payload["requirement_id"] > 0
    assert outcome.result_payload["run_id"] > 0
    assert "simulation-get" in outcome.error.message
    req.assert_called_once()
    run.assert_called_once()
    assert db.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0] == 1
