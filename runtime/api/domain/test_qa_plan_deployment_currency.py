"""Plan edits expose drift in deployment-stage materializations."""

from runtime.api.domain.test_qa_plan_case_currency import (
    _correct_the_case,
    _materialized,
)
from runtime.api.fixtures.backlog_qa_inserts import insert_qa_requirement
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain.deployment_qa_admission_materialization import (
    admitted_requirement_case_key,
)
from yoke_core.domain.qa_plan_case_currency import plan_drift_report


def _admitted_copy(conn, *, source_id: int, run_id: str, item_id: int) -> int:
    """One executing run holding a member-stage copy of a materialized row."""
    conn.execute(
        "INSERT INTO deployment_flows(id,project_id,name,description,stages,"
        "created_at,status,definition_schema_version) VALUES "
        "(%s,1,'Currency flow','','[]','2026-09-20T00:00:00Z','disabled',2)",
        (f"flow-{run_id}",),
    )
    conn.execute(
        "INSERT INTO deployment_runs(id,project_id,flow,status,created_at) "
        "VALUES (%s,1,%s,'executing','2026-09-20T00:00:00Z')",
        (run_id, f"flow-{run_id}"),
    )
    conn.commit()
    source = conn.execute(
        "SELECT method_id,method_name,runner_id,verdict_path,instructions,"
        "expected_outcome,method_config FROM qa_requirements WHERE id=%s",
        (int(source_id),),
    ).fetchone()
    copy = insert_qa_requirement(
        conn,
        item_id=None,
        deployment_run_id=run_id,
        deployment_stage="item-qa",
        deployment_member_item_id=item_id,
        qa_kind="release_qa",
        qa_phase="post_deploy",
        requirement_source="flow_derived",
        plan_case_key=admitted_requirement_case_key(int(source_id)),
        **{key: source[key] for key in source.keys()},
    )
    return int(copy["id"])


def test_plan_edit_reports_unsettled_deployment_requirement():
    with test_database() as conn:
        plan_id, source_id = _materialized(conn, item_id=8615)
        copy_id = _admitted_copy(
            conn, source_id=source_id, run_id="currency-direct-stage", item_id=8615
        )
        conn.execute(
            "UPDATE qa_requirements SET plan_id=%s,plan_case_key='command' WHERE id=%s",
            (plan_id, copy_id),
        )
        conn.execute(
            "INSERT INTO deployment_run_items(run_id,item_id,added_at) VALUES (%s,%s,'2026-09-20T00:00:00Z')",
            ("currency-direct-stage", 8615),
        )
        _correct_the_case(conn, plan_id)
        behind = plan_drift_report(conn, plan_id)["requirements_behind_plan"]
        row = next(row for row in behind if row["requirement_id"] == copy_id)
        assert row["state"] == "stale"
        assert "instructions" in row["diverging_fields"]
        assert "--stage item-qa" in row["recovery"]
        assert f"--plan {plan_id}" in row["recovery"]
