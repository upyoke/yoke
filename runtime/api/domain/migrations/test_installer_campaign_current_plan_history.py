"""Historical snapshot safety for installer campaign convergence."""

from __future__ import annotations

import json

import pytest

from runtime.api.fixtures.backlog_qa_inserts import (
    insert_qa_requirement,
    insert_qa_run,
)
from yoke_core.domain.installer_campaign_current_text_cases import (
    CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES,
)
from yoke_core.domain.migrations.installer_campaign_current_plan import (
    apply,
    invariants,
)


def _plan_id(conn) -> int:
    row = conn.execute(
        "SELECT p.id FROM qa_plans p JOIN projects pr ON pr.id=p.project_id "
        "WHERE pr.slug='yoke' AND p.slug='installer-campaign'"
    ).fetchone()
    assert row is not None
    return int(row[0])


def _future_state(conn) -> list[tuple]:
    return [
        tuple(row)
        for row in conn.execute(
            "SELECT c.case_key,c.position,c.method_id,c.instructions,"
            "c.expected_outcome,c.method_config,c.host_baselines,"
            "c.entry_surface,c.required_completion "
            "FROM qa_plans p JOIN qa_plan_cases c ON c.plan_id=p.id "
            "WHERE p.id=%s ORDER BY c.position",
            (_plan_id(conn),),
        ).fetchall()
    ]


def _insert_complete_requirement(
    conn,
    *,
    plan_id: int,
    run_id: str,
    case_key: str = "welcome-frame",
):
    case = next(
        case
        for case in CURRENT_TEXT_INSTALLER_CAMPAIGN_CASES
        if case["case_key"] == case_key
    )
    method = conn.execute(
        "SELECT name,executor_id,required_capability_kind,verdict_path "
        "FROM qa_methods WHERE id=%s",
        (case["method_id"],),
    ).fetchone()
    return insert_qa_requirement(
        conn,
        item_id=None,
        deployment_run_id=run_id,
        plan_id=plan_id,
        plan_case_key=case["case_key"],
        case_position=case["position"],
        baseline_position=1,
        host_baseline=case["host_baselines"][0] if case["host_baselines"] else None,
        method_id=case["method_id"],
        method_name=method[0],
        executor_id=method[1],
        required_capability_kind=method[2],
        verdict_path=method[3],
        entry_surface=case["entry_surface"],
        required_completion=case["required_completion"],
        instructions=case["instructions"],
        expected_outcome=case["expected_outcome"],
        method_config=json.dumps(case["method_config"], sort_keys=True),
    )


def test_materialized_requirement_history_is_preserved(test_db) -> None:
    apply(test_db)
    plan_id = _plan_id(test_db)
    requirement = _insert_complete_requirement(
        test_db, plan_id=plan_id, run_id="run-history"
    )
    run = insert_qa_run(
        test_db,
        qa_requirement_id=requirement[0],
        executor_type="host_control",
        qa_kind="plan_case",
        raw_result='{"historical":true}',
    )
    artifact = test_db.execute(
        "INSERT INTO qa_artifacts("
        "qa_run_id,artifact_type,content_type,artifact_handle,metadata,created_at"
        ") VALUES (%s,%s,%s,%s,%s,%s) RETURNING *",
        (
            run[0],
            "screenshot",
            "image/png",
            "historical://installer",
            '{"historical":true}',
            "2026-01-01T00:00:00Z",
        ),
    ).fetchone()
    execution = test_db.execute(
        "INSERT INTO qa_plan_executions("
        "id,deployment_run_id,session_id,roster_digest,roster_json,"
        "cursor_ordinal,state,created_at,heartbeat_at"
        ") VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *",
        (
            "qpe-history",
            "run-history",
            "session-history",
            "historical-digest",
            json.dumps([{"ordinal": 1, "requirement_id": requirement[0]}]),
            1,
            "active",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:01Z",
        ),
    ).fetchone()
    execution_result = test_db.execute(
        "INSERT INTO qa_plan_execution_results("
        "execution_id,ordinal,requirement_id,result_json,completed_at"
        ") VALUES (%s,%s,%s,%s,%s) RETURNING *",
        (
            "qpe-history",
            1,
            requirement[0],
            '{"historical":true}',
            "2026-01-01T00:00:02Z",
        ),
    ).fetchone()
    test_db.commit()
    before = {
        "requirement": tuple(requirement),
        "run": tuple(run),
        "artifact": tuple(artifact),
        "execution": tuple(execution),
        "execution_result": tuple(execution_result),
    }
    test_db.execute(
        "UPDATE qa_plan_cases SET instructions='Retired instructions' "
        "WHERE plan_id=%s",
        (plan_id,),
    )
    test_db.commit()

    apply(test_db)
    invariants(test_db)

    after = {
        "requirement": tuple(
            test_db.execute(
                "SELECT * FROM qa_requirements WHERE id=%s", (requirement[0],)
            ).fetchone()
        ),
        "run": tuple(
            test_db.execute(
                "SELECT * FROM qa_runs WHERE id=%s", (run[0],)
            ).fetchone()
        ),
        "artifact": tuple(
            test_db.execute(
                "SELECT * FROM qa_artifacts WHERE id=%s", (artifact[0],)
            ).fetchone()
        ),
        "execution": tuple(
            test_db.execute(
                "SELECT * FROM qa_plan_executions WHERE id='qpe-history'"
            ).fetchone()
        ),
        "execution_result": tuple(
            test_db.execute(
                "SELECT * FROM qa_plan_execution_results "
                "WHERE execution_id='qpe-history' AND ordinal=1"
            ).fetchone()
        ),
    }
    assert after == before


@pytest.mark.parametrize(
    "missing_field",
    (
        "method_id",
        "method_name",
        "executor_id",
        "required_capability_kind",
        "verdict_path",
        "plan_case_key",
        "case_position",
        "baseline_position",
        "instructions",
        "expected_outcome",
        "method_config",
        "entry_surface",
        "required_completion",
    ),
)
def test_incomplete_history_blocks_every_catalog_mutation(
    test_db,
    missing_field: str,
) -> None:
    apply(test_db)
    plan_id = _plan_id(test_db)
    requirement = _insert_complete_requirement(
        test_db, plan_id=plan_id, run_id="run-incomplete-history"
    )
    test_db.execute(
        f"UPDATE qa_requirements SET {missing_field}=NULL WHERE id=%s",
        (requirement[0],),
    )
    test_db.execute(
        "UPDATE qa_plans SET name='Blocked old name' WHERE id=%s",
        (plan_id,),
    )
    test_db.execute(
        "UPDATE qa_methods SET name='Blocked old method' "
        "WHERE id='terminal-inspection'"
    )
    test_db.execute(
        "UPDATE qa_plan_cases SET instructions='Blocked old instructions' "
        "WHERE plan_id=%s AND case_key='welcome-frame'",
        (plan_id,),
    )
    test_db.commit()
    before = {
        "plan": tuple(
            test_db.execute(
                "SELECT * FROM qa_plans WHERE id=%s", (plan_id,)
            ).fetchone()
        ),
        "method": tuple(
            test_db.execute(
                "SELECT * FROM qa_methods WHERE id='terminal-inspection'"
            ).fetchone()
        ),
        "cases": _future_state(test_db),
    }

    with pytest.raises(
        RuntimeError,
        match="1 installer campaign requirement snapshots are incomplete",
    ):
        apply(test_db)

    after = {
        "plan": tuple(
            test_db.execute(
                "SELECT * FROM qa_plans WHERE id=%s", (plan_id,)
            ).fetchone()
        ),
        "method": tuple(
            test_db.execute(
                "SELECT * FROM qa_methods WHERE id='terminal-inspection'"
            ).fetchone()
        ),
        "cases": _future_state(test_db),
    }
    assert after == before


def test_baseline_variant_history_requires_named_host_baseline(test_db) -> None:
    apply(test_db)
    plan_id = _plan_id(test_db)
    requirement = _insert_complete_requirement(
        test_db,
        plan_id=plan_id,
        run_id="run-baseline-history",
        case_key="path-on-shell",
    )
    test_db.execute(
        "UPDATE qa_requirements SET host_baseline=NULL WHERE id=%s",
        (requirement[0],),
    )
    test_db.commit()

    with pytest.raises(RuntimeError, match="snapshots are incomplete"):
        apply(test_db)


def test_retired_historical_method_and_baseline_remain_self_describing(
    test_db,
) -> None:
    apply(test_db)
    plan_id = _plan_id(test_db)
    requirement = _insert_complete_requirement(
        test_db,
        plan_id=plan_id,
        run_id="run-retired-history",
        case_key="path-on-shell",
    )
    test_db.execute(
        "UPDATE qa_requirements SET method_id=%s, method_name=%s, "
        "host_baseline=%s, method_config=%s WHERE id=%s",
        (
            "retired-machine-state-check",
            "Retired machine state check",
            "retired-host",
            '{"baseline_configs":{"retired-host":{"retired":true}}}',
            requirement[0],
        ),
    )
    test_db.commit()
    before = tuple(
        test_db.execute(
            "SELECT * FROM qa_requirements WHERE id=%s",
            (requirement[0],),
        ).fetchone()
    )

    apply(test_db)
    invariants(test_db)

    after = tuple(
        test_db.execute(
            "SELECT * FROM qa_requirements WHERE id=%s",
            (requirement[0],),
        ).fetchone()
    )
    assert after == before
