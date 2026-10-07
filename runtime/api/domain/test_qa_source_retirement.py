"""A corrected body retires the post-deploy item source it replaces.

A post_deploy item requirement never runs itself; each release admits a
frozen copy and grades only that. When the copy fails because the source
was worded wrong, a corrected run case superseding the copy settles that run
alone, and the source keeps the broken body for every later release. These
walk the whole correction on that shape: the corrected run case passes, the
source is retired in favor of a corrected item requirement in one
supersession, the run's passing case still answers done, and the next
release admits only the corrected body.

Recording the corrected item requirement is a control-plane write, so the
control plane may record a case for any environment its project owns; only
executing it checks that the runtime may observe that environment.
"""

from __future__ import annotations

import pytest

from runtime.api.domain.test_dash_post_deploy_review_isolation import _insert_dash
from runtime.api.domain.test_deployment_qa_admission_execution import (
    _seed_selected_requirement_run,
)
from runtime.api.domain.test_release_member_target_enrollment import _pair
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
from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_case_key,
)
from yoke_core.domain.deployment_qa_source_obligation import source_obligation_consumed
from yoke_core.domain.deployment_qa_stage_gate import deployment_qa_stage_status
from yoke_core.domain.qa_requirement_supersession import (
    QaSupersessionError,
    supersede_requirement,
)

CORRECTED_INSTRUCTIONS = "Open the release workbench and capture its ready state."


def _corrected_item_requirement(conn, *, source_id: int) -> int:
    """The source's own subject and target with a corrected body."""
    columns = [
        str(row[0])
        for row in conn.execute(
            "SELECT column_name FROM information_schema.columns "
            "WHERE table_name='qa_requirements' AND column_name<>'id' "
            "ORDER BY ordinal_position"
        ).fetchall()
    ]
    projected = [
        "%s"
        if column == "instructions"
        else "NULL"
        if column.startswith("supersed") or column == "replacement_requirement_id"
        else column
        for column in columns
    ]
    row = conn.execute(
        f"INSERT INTO qa_requirements({','.join(columns)}) "
        f"SELECT {','.join(projected)} FROM qa_requirements WHERE id=%s "
        "RETURNING id",
        (CORRECTED_INSTRUCTIONS, int(source_id)),
    ).fetchone()
    conn.commit()
    return int(row["id"])


def _retire(conn, *, source_id: int, corrected_id: int) -> dict:
    return supersede_requirement(
        conn,
        requirement_id=source_id,
        superseded_by_requirement_id=corrected_id,
        rationale="the source named the wrong route; the corrected body passed",
        source="agent",
    )


def test_corrected_run_case_retires_its_source_and_done_converges(test_db) -> None:
    item_id = 2370
    run_id = "run-retire-source"
    _insert_dash(test_db, item_id=item_id, status="release")
    source_id, copy_id, run_case_id = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id=run_id, corrected=True
    )
    copy_receipt = supersede_requirement(
        test_db,
        requirement_id=copy_id,
        superseded_by_requirement_id=run_case_id,
        rationale="the admitted copy carried the broken wording",
        source="agent",
    )
    notice = copy_receipt["next_admission_notice"]
    assert f"supersede --requirement-id {source_id}" in notice
    assert "yoke qa requirement add --item" in notice
    assert "update" not in notice
    assert deployment_qa_stage_status(
        test_db, run_id=run_id, stage_name=MEMBER_QA_STAGE, member_item_id=item_id
    )["accepted"]

    corrected_id = _corrected_item_requirement(test_db, source_id=source_id)
    receipt = _retire(test_db, source_id=source_id, corrected_id=corrected_id)

    assert receipt["superseded_by_requirement_id"] == corrected_id
    assert receipt["run_replacement_requirement_id"] == run_case_id
    succeed_run(test_db, run_id)
    # The run that admitted the retired source answers the corrected one.
    assert source_obligation_consumed(
        test_db, item_id=item_id, source_requirement_id=corrected_id
    )
    assert (
        evaluate(item_id=item_id, target_status="done", db_path=str(test_db.info.dsn))
        is None
    )

    # A later release admits only the corrected body.
    next_run = "run-retire-source-next"
    _seed_selected_requirement_run(
        test_db, run_id=next_run, item_id=item_id, requirement_id=corrected_id
    )
    admissible = admissible_post_deploy_requirement_ids(
        test_db, run_id=next_run, item_id=item_id
    )
    assert corrected_id in admissible
    assert source_id not in admissible
    next_copy = admitted_copy(test_db, run_id=next_run, item_id=item_id)
    row = test_db.execute(
        "SELECT plan_case_key,instructions FROM qa_requirements WHERE id=%s",
        (next_copy,),
    ).fetchone()
    assert str(row["plan_case_key"]) == admitted_requirement_case_key(corrected_id)
    assert row["instructions"] == CORRECTED_INSTRUCTIONS
    # The source row itself is never rewritten; the link is the record.
    source = test_db.execute(
        "SELECT instructions,superseded_by_requirement_id FROM qa_requirements "
        "WHERE id=%s",
        (source_id,),
    ).fetchone()
    assert source["instructions"] != CORRECTED_INSTRUCTIONS
    assert source["superseded_by_requirement_id"] == corrected_id


def test_source_without_a_passing_run_correction_is_not_retired(test_db) -> None:
    item_id = 2371
    _insert_dash(test_db, item_id=item_id, status="release")
    source_id, _copy_id, _ = deliver_with_failing_admitted_copy(
        test_db, item_id=item_id, run_id="run-retire-unproven", corrected=False
    )
    corrected_id = _corrected_item_requirement(test_db, source_id=source_id)

    with pytest.raises(QaSupersessionError) as refusal:
        _retire(test_db, source_id=source_id, corrected_id=corrected_id)

    assert "--replaces" in str(refusal.value)
    stored = test_db.execute(
        "SELECT superseded_by_requirement_id FROM qa_requirements WHERE id=%s",
        (source_id,),
    ).fetchone()[0]
    assert stored is None


def _restrict_prod_runtime(conn, monkeypatch) -> None:
    monkeypatch.setenv("YOKE_ENVIRONMENT", "prod")
    conn.execute(
        "UPDATE environments SET settings=%s WHERE project_id=1 AND name='prod'",
        ('{"qa":{"restrict_execution_to_self":true}}',),
    )
    conn.commit()


def test_prod_records_a_stage_requirement_but_does_not_execute_it(
    test_db, monkeypatch
) -> None:
    from yoke_core.domain.qa_environment_execution_target import (
        bind_item_named_target,
        resolve_named_environment_execution_target,
    )
    from yoke_core.domain.qa_execution_environment_target import (
        QaExecutionTargetError,
    )

    item_id = 2372
    _pair(test_db, item_id=item_id)
    _restrict_prod_runtime(test_db, monkeypatch)

    row = {"target_env": "stage"}
    assert bind_item_named_target(test_db, item_id=item_id, row=row) == ""
    assert row["execution_target_digest"]

    with pytest.raises(QaExecutionTargetError, match="cannot execute QA target"):
        resolve_named_environment_execution_target(
            test_db, project_id=1, environment_name="stage"
        )


def test_prod_rebinds_a_requirement_to_stage(test_db, monkeypatch) -> None:
    from yoke_core.domain.qa_requirement_config_update import apply_requirement_update

    item_id = 2373
    sources = _pair(test_db, item_id=item_id)
    _restrict_prod_runtime(test_db, monkeypatch)

    outcome = apply_requirement_update(test_db, sources["prod"], "target_env", "stage")

    assert outcome.ok, f"{outcome.error_code}: {outcome.message}"
    stored = test_db.execute(
        "SELECT target_env,execution_target_digest FROM qa_requirements WHERE id=%s",
        (sources["prod"],),
    ).fetchone()
    assert stored["target_env"] == "stage"
    assert stored["execution_target_digest"]
