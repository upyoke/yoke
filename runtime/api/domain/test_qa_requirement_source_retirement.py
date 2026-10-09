"""Retirement resolves a plan destination and proves the final correction."""

import pytest

from runtime.api.domain.test_dash_post_deploy_review_isolation import _insert_dash
from runtime.api.domain.test_deployment_qa_stage_execution import _plan
from runtime.api.domain.test_qa_source_retirement import _retire
from runtime.api.fixtures.deployment_admitted_case_fixture import (
    corrected_sibling,
    deliver_with_failing_admitted_copy,
    intake_requirement,
)
from runtime.api.fixtures.deployment_scoped_qa_run_fixture import record_case_verdict
from yoke_core.domain.qa_requirement_replacement import declare_existing_replacement
from yoke_core.domain.qa_requirement_supersession import (
    QaSupersessionError,
    requirement_scope,
    same_scope,
)


def _plan_source_with_replacement_chain(conn, *, final_verdict):
    item_id = 2390
    _insert_dash(conn, item_id=item_id, status="release")
    source, copy, _ = deliver_with_failing_admitted_copy(
        conn, item_id=item_id, run_id="run-plan-source-correction", corrected=False
    )
    plan = _plan(conn, "source-correction")
    # A plan source preserves plan/case identity and the frozen destination.
    conn.execute(
        "UPDATE qa_requirements SET plan_id=%s,plan_case_key='command-smoke' "
        "WHERE id IN (%s,%s)",
        (plan, source, copy),
    )
    conn.execute(
        "UPDATE qa_requirements SET target_env=NULL,"
        "execution_target_json=c.execution_target_json,"
        "execution_target_digest=c.execution_target_digest "
        "FROM qa_requirements c WHERE qa_requirements.id=%s AND c.id=%s",
        (source, copy),
    )
    conn.commit()
    middle = corrected_sibling(conn, broken_id=copy)
    declare_existing_replacement(conn, failed_id=copy, replacement_id=middle)
    record_case_verdict(conn, middle, "fail", evidence=False)
    conn.execute(
        "UPDATE qa_requirements SET plan_case_key='intermediate-correction' WHERE id=%s",
        (middle,),
    )
    conn.commit()
    final = corrected_sibling(conn, broken_id=middle)
    declare_existing_replacement(conn, failed_id=middle, replacement_id=final)
    record_case_verdict(conn, final, final_verdict, evidence=final_verdict == "pass")
    # Hand-added item corrections carry a named environment, no plan snapshot.
    corrected = intake_requirement(conn, item_id=item_id)
    conn.execute(
        "UPDATE qa_requirements SET target_env='stage',plan_id=NULL,plan_case_key=NULL,"
        "execution_target_json=NULL,execution_target_digest=NULL WHERE id=%s",
        (corrected,),
    )
    conn.commit()
    return source, corrected, final


def test_plan_source_retires_to_named_environment_after_replacement_chain(test_db):
    source, corrected, final = _plan_source_with_replacement_chain(
        test_db, final_verdict="pass"
    )
    rows = [
        dict(
            test_db.execute(
                "SELECT * FROM qa_requirements WHERE id=%s", (rid,)
            ).fetchone()
        )
        for rid in (source, corrected)
    ]
    assert rows[0]["execution_target_digest"]
    assert not rows[1]["execution_target_digest"]
    assert requirement_scope(rows[0]) == requirement_scope(rows[1])
    receipt = _retire(test_db, source_id=source, corrected_id=corrected)
    assert receipt["run_replacement_requirement_id"] == final
    assert receipt["superseded_by_requirement_id"] == corrected


@pytest.mark.parametrize(
    "environment,verdict,reason",
    [
        ("prod", "pass", "target environment differs"),
        ("stage", "fail", "source_retirement_unproven"),
    ],
)
def test_source_retirement_refuses_wrong_environment_or_failing_terminal(
    test_db, environment, verdict, reason
):
    source, corrected, _ = _plan_source_with_replacement_chain(
        test_db, final_verdict=verdict
    )
    test_db.execute(
        "UPDATE qa_requirements SET target_env=%s WHERE id=%s", (environment, corrected)
    )
    test_db.commit()
    with pytest.raises(QaSupersessionError, match=reason):
        _retire(test_db, source_id=source, corrected_id=corrected)
    assert (
        test_db.execute(
            "SELECT superseded_by_requirement_id FROM qa_requirements WHERE id=%s",
            (source,),
        ).fetchone()[0]
        is None
    )


def test_run_bound_supersession_still_requires_exact_snapshot():
    original = {
        "deployment_run_id": "run",
        "target_env": "stage",
        "execution_target_digest": "old",
    }
    corrected = dict(original, execution_target_digest="new")
    assert same_scope(original, corrected) == [
        "execution target differs ('old' vs 'new')"
    ]


@pytest.mark.parametrize(
    "field,value",
    [
        ("item_id", 2),
        ("workflow_transition_id", "done"),
        ("qa_phase", "verification"),
        ("host_baseline", "other"),
    ],
)
def test_source_retirement_keeps_subject_transition_phase_and_baseline(field, value):
    source = {
        "item_id": 1,
        "workflow_transition_id": "release",
        "qa_phase": "post_deploy",
        "target_env": "stage",
    }
    assert same_scope(source, dict(source, **{field: value}))
