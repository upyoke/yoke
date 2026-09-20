"""A corrected plan case, and the row that actually runs.

The defect these cover: a plan case corrected at an operator's explicit
request, a plan that read back correct, and a requirement row that kept the
body it was materialized with until a deployment run froze a copy of it and
the walk failed on the very defect the correction had removed.

Three things have to hold for that to be impossible. An edit has to name the
rows it did not reach. One operation has to bring such a row current, and
refuse by name rather than proceed when something has already frozen a copy of
it. And drift has to be readable without opening two bodies side by side.
"""

from __future__ import annotations

import pytest

from runtime.api.fixtures.backlog_inserts import insert_item
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.qa_plan_attachments import (
    materialize_for_item,
    set_project_default,
)
from yoke_core.domain.qa_plan_case_currency import (
    CURRENT,
    ORPHANED,
    STALE,
    STALE_PLAN_CASE_CODE,
    annotate_plan_currency,
    plan_case_divergence,
    plan_drift_report,
)
from yoke_core.domain.qa_plan_execution_state import begin_plan_execution
from yoke_core.domain.qa_plan_management import (
    QaPlanError,
    create_plan,
    replace_plan_cases,
)
from yoke_core.domain.qa_plan_refresh_safety import LIVE_EXECUTION_CODE
from yoke_core.domain.qa_plan_rematerialize import rematerialize_for_item

TRANSITION = "implemented"
ORIGINAL_INSTRUCTIONS = "Run the target command."
CORRECTED_INSTRUCTIONS = "Run the target command, then settle before asserting."


def _case(**overrides):
    case = {
        "case_key": "command",
        "position": 1,
        "method_id": "command",
        "instructions": ORIGINAL_INSTRUCTIONS,
        "expected_outcome": "The command passes.",
        "method_config": {"command": "true"},
    }
    case.update(overrides)
    return case


def _materialized(conn, *, item_id: int) -> tuple[int, int]:
    """One item requirement materialized from a one-case plan."""
    insert_item(conn, id=item_id, title="Run targeted QA", workflow_id="issue")
    plan = create_plan(
        conn,
        project="yoke",
        slug=f"currency-plan-{item_id}",
        name="Currency plan",
    )
    plan_id = int(plan["id"])
    replace_plan_cases(conn, plan_id=plan_id, cases=[_case()])
    set_project_default(
        conn, plan_id=plan_id, workflow_id="issue", transition_id=TRANSITION
    )
    result = materialize_for_item(conn, item_id=item_id, transition_id=TRANSITION)
    return plan_id, int(result["created_requirement_ids"][0])


def _correct_the_case(conn, plan_id: int) -> dict:
    return replace_plan_cases(
        conn,
        plan_id=plan_id,
        cases=[_case(instructions=CORRECTED_INSTRUCTIONS)],
    )


def _instructions(conn, requirement_id: int) -> str:
    return str(
        conn.execute(
            "SELECT instructions FROM qa_requirements WHERE id=%s",
            (int(requirement_id),),
        ).fetchone()["instructions"]
    )


def test_a_materialized_row_starts_current_with_its_plan() -> None:
    """Nothing is reported behind a plan nobody has edited."""
    with test_database() as conn:
        plan_id, requirement_id = _materialized(conn, item_id=8601)

        assert plan_case_divergence(conn, requirement_id) is None
        assert plan_drift_report(conn, plan_id)["requirements_behind_plan"] == []


def test_correcting_a_plan_case_names_the_rows_now_behind_it() -> None:
    """The edit that used to land silently now says what it did not reach."""
    with test_database() as conn:
        plan_id, requirement_id = _materialized(conn, item_id=8602)
        _correct_the_case(conn, plan_id)

        report = plan_drift_report(conn, plan_id)
        behind = report["requirements_behind_plan"]

    assert report["requirements_behind_plan_count"] == 1
    assert behind[0]["requirement_id"] == requirement_id
    assert behind[0]["state"] == STALE
    assert behind[0]["diverging_fields"] == ["instructions"]
    # The row is named, and so is the command that reaches this exact row.
    assert STALE_PLAN_CASE_CODE in behind[0]["recovery"]
    assert "yoke qa plan rematerialize --item" in behind[0]["recovery"]
    assert f"--transition {TRANSITION}" in behind[0]["recovery"]


def test_the_named_refresh_actually_brings_the_row_current() -> None:
    """The remedy the refusal names is one the caller can really take."""
    with test_database() as conn:
        plan_id, requirement_id = _materialized(conn, item_id=8603)
        _correct_the_case(conn, plan_id)
        assert _instructions(conn, requirement_id) == ORIGINAL_INSTRUCTIONS

        rematerialize_for_item(conn, item_id=8603, transition_id=TRANSITION)

        # instructions is not in the qa.requirement.update allowlist at all;
        # this path reaches it because it rewrites the derivation whole.
        assert _instructions(conn, requirement_id) == CORRECTED_INSTRUCTIONS
        assert plan_case_divergence(conn, requirement_id) is None
        assert plan_drift_report(conn, plan_id)["requirements_behind_plan"] == []


def test_a_refresh_refuses_while_a_live_execution_holds_the_roster() -> None:
    """A walk in progress is a frozen copy; the refresh refuses before writing."""
    with test_database() as conn:
        plan_id, requirement_id = _materialized(conn, item_id=8604)
        _correct_the_case(conn, plan_id)
        execution = begin_plan_execution(
            conn,
            item_id=8604,
            transition_id=TRANSITION,
            actor_id="op",
            session_id="session-currency",
        )

        with pytest.raises(QaPlanError) as excinfo:
            rematerialize_for_item(conn, item_id=8604, transition_id=TRANSITION)
        message = str(excinfo.value)

        # Refused before any write: the row is exactly as it was.
        assert _instructions(conn, requirement_id) == ORIGINAL_INSTRUCTIONS

    assert LIVE_EXECUTION_CODE in message
    assert str(execution["id"]) in message
    # The recovery names the whole invocation, not the bare command, because
    # the bare command answers with a usage error rather than an abort.
    assert "yoke qa plan abort --item" in message
    assert f"--execution-id {execution['id']}" in message


def test_a_row_whose_case_left_the_plan_reads_as_orphaned() -> None:
    """A row the plan no longer carries is named too, with its own route."""
    with test_database() as conn:
        plan_id, requirement_id = _materialized(conn, item_id=8605)
        replace_plan_cases(
            conn, plan_id=plan_id, cases=[_case(case_key="renamed-command")]
        )

        divergence = plan_case_divergence(conn, requirement_id)

    assert divergence is not None
    assert divergence.state == ORPHANED
    assert divergence.fields == ()
    assert "no longer carries case 'command'" in divergence.message()


def test_the_requirement_reader_names_drift_without_a_second_body() -> None:
    """Drift is read off the row, not inferred by comparing two bodies."""
    with test_database() as conn:
        plan_id, requirement_id = _materialized(conn, item_id=8606)
        rows = [
            {"id": requirement_id, "plan_id": plan_id},
        ]
        assert annotate_plan_currency(conn, rows)[0]["plan_currency"] == CURRENT

        _correct_the_case(conn, plan_id)
        annotated = annotate_plan_currency(
            conn, [{"id": requirement_id, "plan_id": plan_id}]
        )

    assert annotated[0]["plan_currency"] == STALE
    assert annotated[0]["plan_diverging_fields"] == ["instructions"]


def test_a_row_from_no_plan_is_left_alone_by_the_reader() -> None:
    """An ad-hoc or admitted row has no plan case to be behind."""
    with test_database() as conn:
        _materialized(conn, item_id=8607)
        rows = annotate_plan_currency(conn, [{"id": 1, "plan_id": None}])

    assert "plan_currency" not in rows[0]
