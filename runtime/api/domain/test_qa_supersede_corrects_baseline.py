"""An operator corrects a QA case whose declared host baseline was wrong.

A case that needs Yoke on its host but declares ``fresh-host`` can never be
corrected in place once a copy ran, and a plain supersession refuses a
replacement at another baseline because the baseline is part of the scope.
``corrects_baseline`` is that one correction: the operator supersedes the
broken admitted copy and retires its item source with cases at the right
baseline, the gate reads the stored links as valid, and the next release
admits the corrected baseline. The broken rows stay as history.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.dash_post_deploy_review_isolation_test_support import (
    _insert_dash,
)
from runtime.api.domain.deployment_qa_admission_execution_test_support import (
    _seed_selected_requirement_run,
)
from runtime.api.domain.qa_source_retirement_test_support import (
    _corrected_item_requirement,
)
from runtime.api.fixtures.deployment_admitted_case_fixture import (
    MEMBER_QA_STAGE,
    admitted_copy,
    deliver_with_failing_admitted_copy,
    succeed_run,
)
from yoke_core.domain.dash_posture_gate import evaluate
from yoke_core.domain.deployment_member_post_deploy_admission import (
    admissible_post_deploy_requirement_ids,
)
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.qa_requirement_supersession import (
    QaSupersessionError,
    supersede_requirement,
)

WRONG = "fresh-host"
RIGHT = "shell-preconfigured"


def _baseline(conn, requirement_id: int, baseline: str) -> None:
    conn.execute(
        "UPDATE qa_requirements SET host_baseline=%s WHERE id=%s",
        (baseline, int(requirement_id)),
    )
    conn.commit()


def _delivered(conn, *, item_id: int, run_id: str) -> tuple[int, int, int]:
    _insert_dash(conn, item_id=item_id, status="release")
    source_id, copy_id, run_case_id = deliver_with_failing_admitted_copy(
        conn, item_id=item_id, run_id=run_id, corrected=True
    )
    for requirement_id, baseline in ((source_id, WRONG), (copy_id, WRONG), (run_case_id, RIGHT)):
        _baseline(conn, requirement_id, baseline)
    return source_id, copy_id, run_case_id


def _supersede(conn, broken: int, corrected: int, **options) -> dict:
    return supersede_requirement(
        conn,
        requirement_id=broken,
        superseded_by_requirement_id=corrected,
        rationale="the mission runs Yoke on the host, so it needs shell-preconfigured",
        **options,
    )


def test_operator_corrects_the_baseline_of_a_copy_and_its_source(test_db) -> None:
    item_id, run_id = 2470, "run-corrects-baseline"
    source_id, copy_id, run_case_id = _delivered(test_db, item_id=item_id, run_id=run_id)

    with pytest.raises(QaSupersessionError, match="host baseline differs.*--corrects-baseline"):
        _supersede(test_db, copy_id, run_case_id, source="operator")
    with pytest.raises(QaSupersessionError, match="baseline_correction_refused.*--source operator"):
        _supersede(test_db, copy_id, run_case_id, source="agent", corrects_baseline=True)

    receipt = _supersede(
        test_db, copy_id, run_case_id, source="operator", corrects_baseline=True
    )
    assert receipt["supersession_corrects_baseline"] is True
    # The gate walks the stored link and accepts it across baselines.
    assert deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name=MEMBER_QA_STAGE, member_item_id=item_id
    )["accepted"]

    corrected_id = _corrected_item_requirement(test_db, source_id=source_id)
    _baseline(test_db, corrected_id, RIGHT)
    # Like YOK-5392's case, the corrected source is a Test Machine mission.
    test_db.execute(
        "UPDATE qa_requirements SET method_id='exploratory-mission',"
        "method_name='Exploratory mission',runner_id='agent_mission',"
        "starting_state='baseline',method_config=%s WHERE id=%s",
        ('{"executor":"informed_subagent","test_machine":"windows-native-lab"}', corrected_id),
    )
    test_db.commit()
    retired = _supersede(
        test_db, source_id, corrected_id, source="operator", corrects_baseline=True
    )
    assert retired["run_replacement_requirement_id"] == run_case_id
    succeed_run(test_db, run_id)
    assert evaluate(item_id=item_id, target_status="done", db_path=str(test_db.info.dsn)) is None

    # The broken rows stay as history, each marking its baseline fix.
    rows = test_db.execute(
        "SELECT id,host_baseline,superseded_by_requirement_id,supersession_corrects_baseline "
        "FROM qa_requirements WHERE id IN (%s,%s) ORDER BY id",
        (source_id, copy_id),
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        (source_id, WRONG, corrected_id, True),
        (copy_id, WRONG, run_case_id, True),
    ]

    # The next release admits only the corrected baseline.
    next_run = "run-corrects-baseline-next"
    _seed_selected_requirement_run(
        test_db, run_id=next_run, item_id=item_id, requirement_id=corrected_id
    )
    admissible = admissible_post_deploy_requirement_ids(
        test_db, run_id=next_run, item_id=item_id
    )
    assert corrected_id in admissible and source_id not in admissible
    next_copy = admitted_copy(test_db, run_id=next_run, item_id=item_id)
    assert test_db.execute(
        "SELECT host_baseline FROM qa_requirements WHERE id=%s", (next_copy,)
    ).fetchone()[0] == RIGHT


def test_a_baseline_correction_needs_a_different_named_baseline(test_db) -> None:
    _source_id, copy_id, run_case_id = _delivered(
        test_db, item_id=2471, run_id="run-corrects-baseline-same"
    )
    _baseline(test_db, run_case_id, WRONG)
    with pytest.raises(QaSupersessionError, match="no baseline to correct"):
        _supersede(test_db, copy_id, run_case_id, source="operator", corrects_baseline=True)

    test_db.execute("UPDATE qa_requirements SET host_baseline=NULL WHERE id=%s", (run_case_id,))
    test_db.commit()
    with pytest.raises(QaSupersessionError, match="names no host baseline"):
        _supersede(test_db, copy_id, run_case_id, source="operator", corrects_baseline=True)
    assert test_db.execute(
        "SELECT superseded_by_requirement_id FROM qa_requirements WHERE id=%s", (copy_id,)
    ).fetchone()[0] is None
