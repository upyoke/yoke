"""Enrollment shares fresh locked inputs without weakening snapshot validation."""

import json
from types import SimpleNamespace

import pytest

from runtime.api.domain.test_deployment_qa_stage_execution import (
    _plan,
    _seed_run,
    _stages,
)
from runtime.api.domain.test_deployment_qa_shared_plans import _attach
from runtime.api.domain.test_deployment_shipping_reads import CountedConnection
from runtime.api.fixtures.backlog_inserts import insert_qa_requirement
from yoke_core.domain.deployment_admission_reads import (
    read_enrollment_inputs,
    read_snapshot_inputs,
)
from yoke_core.domain.deployment_requirement_snapshots import (
    requirement_selection,
    snapshot_member_requirements,
)
from yoke_core.domain.schema_read_scope import composition_reads


RUN = "admission-inputs"
MEMBERS = (32001, 32002, 32003)


@pytest.fixture
def admission_catalog(test_db):
    plan = _plan(test_db)
    stages = _stages(plan)
    stages[1].pop("cases")
    _seed_run(test_db, run_id=RUN, stages=stages, members=MEMBERS)
    requirements = {}
    for member in MEMBERS:
        _attach(test_db, member, plan)
        row = insert_qa_requirement(
            test_db,
            item_id=member,
            qa_phase="post_deploy",
            target_env="stage",
        )
        requirements[member] = int(row["id"])
    return plan, requirements


def _snapshots(conn, selections, admission=None):
    return {
        member: json.loads(
            snapshot_member_requirements(
                conn,
                run_id=RUN,
                item_id=member,
                selection_json=requirement_selection(requirement_ids=ids),
                admission=admission,
            )
        )
        for member, ids in selections.items()
    }


def test_enrollment_reads_each_intake_and_plan_once_and_refreshes_after_rollback(
    test_db,
    admission_catalog,
):
    plan, requirements = admission_catalog
    selections = {member: (value,) for member, value in requirements.items()}
    baseline = _snapshots(test_db, selections)
    test_db.rollback()
    conn = CountedConnection(test_db)
    # Creation shares immutable repository facts across these two passes.
    # Mutable admission inputs must still be read again after its rollback.
    with composition_reads():
        selected, inputs = read_enrollment_inputs(conn, run_id=RUN, item_ids=MEMBERS)
        assert selected == selections
        assert _snapshots(conn, selected, inputs) == baseline
        queries = list(conn.queries)
        intake = [sql for sql in queries if "FROM qa_requirements r " in sql]
        requirements_sql = [
            sql for sql in queries if "FROM qa_requirements WHERE id IN" in sql
        ]
        plans_sql = [sql for sql in queries if "FROM qa_plans WHERE id IN" in sql]
        cases_sql = [sql for sql in queries if "FROM qa_plan_cases c JOIN" in sql]
        for group in (intake, requirements_sql, plans_sql, cases_sql):
            assert len(group) == 1
            assert conn.queries[group[0]] == 1
        assert requirements_sql[0].endswith("ORDER BY id FOR UPDATE")
        assert plans_sql[0].endswith("ORDER BY id FOR UPDATE")
        test_db.rollback()
        test_db.execute(
            "UPDATE qa_requirements SET waived_at=NOW() WHERE id=%s",
            (requirements[MEMBERS[0]],),
        )
        test_db.execute(
            "UPDATE qa_plans SET name='New definition' WHERE id=%s", (plan,)
        )
        test_db.commit()
        selected, inputs = read_enrollment_inputs(conn, run_id=RUN, item_ids=MEMBERS)
        after = _snapshots(conn, selected, inputs)
        assert selected[MEMBERS[0]] == ()
        assert after[MEMBERS[0]]["requirements"] == []
        assert all(
            value["plans"][0]["plan"]["name"] == "New definition"
            for value in after.values()
        )
        assert conn.queries[plans_sql[0]] == 2


@pytest.mark.parametrize(
    "defect,expected",
    [
        ("waived", "is waived"),
        ("foreign_item", "is not owned"),
        ("foreign_run", "belongs to deployment run"),
        ("retired_plan", "is retired"),
        ("empty_plan", "has no runnable cases"),
    ],
)
def test_shared_inputs_preserve_canonical_refusals(
    test_db, admission_catalog, defect, expected
):
    plan, requirements = admission_catalog
    member = MEMBERS[0]
    requirement = requirements[member]
    if defect == "waived":
        test_db.execute(
            "UPDATE qa_requirements SET waived_at=NOW() WHERE id=%s", (requirement,)
        )
    elif defect == "foreign_item":
        test_db.execute(
            "UPDATE qa_requirements SET item_id=%s WHERE id=%s",
            (MEMBERS[1], requirement),
        )
    elif defect == "foreign_run":
        # The same existing run is foreign to the requested successor below.
        test_db.execute(
            "UPDATE qa_requirements SET item_id=NULL,deployment_run_id=%s WHERE id=%s",
            (RUN, requirement),
        )
    elif defect == "retired_plan":
        test_db.execute("UPDATE qa_plans SET retired_at=NOW() WHERE id=%s", (plan,))
    else:
        test_db.execute("DELETE FROM qa_plan_cases WHERE plan_id=%s", (plan,))
    inputs = read_snapshot_inputs(
        test_db,
        item_ids=MEMBERS,
        requirement_ids=requirements.values(),
        plan_ids=(plan,),
    )
    with pytest.raises(ValueError, match=expected):
        snapshot_member_requirements(
            test_db,
            run_id="admission-successor",
            item_id=member,
            selection_json=requirement_selection(
                requirement_ids=(requirement,), plan_ids=(plan,)
            ),
            admission=inputs,
        )


def test_retraction_excludes_requirements_and_withdrawn_plans(
    test_db, admission_catalog
):
    plan, requirements = admission_catalog
    member = MEMBERS[0]
    test_db.execute(
        "UPDATE qa_requirements SET retracted_at=NOW() WHERE id=%s",
        (requirements[member],),
    )
    test_db.execute(
        "UPDATE qa_plan_item_attachments SET retracted_at=NOW() WHERE item_id=%s",
        (member,),
    )
    inputs = read_snapshot_inputs(
        test_db,
        item_ids=MEMBERS,
        requirement_ids=requirements.values(),
        plan_ids=(plan,),
    )
    result = _snapshots(test_db, {member: (requirements[member],)}, inputs)[member]
    assert result["requirements"] == []
    assert result["plans"] == []


def test_progress_handler_flushes_stderr_and_returns_same_records(capsys):
    from yoke_core.domain.deployment_start_timing import (
        PREFIX,
        start_step,
        timed_handler,
        timing_facts,
    )

    @timed_handler(progress=True)
    def handle(request):
        timing_facts(run_id=RUN, source_sha="a" * 40)
        with start_step("create_commit"):
            pass
        return SimpleNamespace(result_payload={})

    result = handle(SimpleNamespace(target=SimpleNamespace(workflow_run_id=None)))
    capture = capsys.readouterr()
    assert capture.out == ""
    records = [
        json.loads(line.removeprefix(PREFIX)) for line in capture.err.splitlines()
    ]
    assert result.result_payload["start_timings"] == records
    assert [record["phase"] for record in records] == ["start", "end"]
    assert all(
        record["run_id"] == RUN and record["source_sha"] == "a" * 40
        for record in records
    )


def test_completion_defaults_are_pinned_before_qa_selection(
    test_db,
    admission_catalog,
    monkeypatch,
):
    from yoke_core.domain import workflow_project_defaults as defaults
    from yoke_core.domain import deployment_member_post_deploy_admission as admission
    from yoke_core.domain.deployment_item_flow_resolution import item_completion_flows

    original_flow = f"flow-{RUN}"
    default = [original_flow]
    monkeypatch.setattr(
        defaults, "get_delivery_default", lambda conn, **kwargs: default[0]
    )
    derive = admission.post_deploy_admission_sets

    def changed_default(conn, **kwargs):
        default[0] = "changed-after-enrollment-began"
        return derive(conn, **kwargs)

    monkeypatch.setattr(admission, "post_deploy_admission_sets", changed_default)
    selected, _ = read_enrollment_inputs(test_db, run_id=RUN, item_ids=MEMBERS)
    assert selected == {
        member: (value,) for member, value in admission_catalog[1].items()
    }
    assert item_completion_flows(test_db, MEMBERS) == dict.fromkeys(
        MEMBERS, original_flow
    )
    assert all(
        row[0] == original_flow
        for row in test_db.execute(
            "SELECT deployment_flow FROM items WHERE id=ANY(%s)",
            (list(MEMBERS),),
        )
    )
