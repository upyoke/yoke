"""Permanent coverage for the deployment-scoped QA cutover."""

from __future__ import annotations

import importlib

import pytest

from yoke_core.domain import db_backend
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.qa_deployment_scope_schema import (
    EXECUTION_SCOPE_INDEX_NAMES,
    EXECUTION_SUBJECT_CONSTRAINT,
    LEGACY_EXECUTION_SUBJECT_EXPRESSION,
    REQUIREMENT_SCOPE_INDEX_NAMES,
    _canonical_sql,
    assert_deployment_scope_contract,
)
from yoke_core.domain.qa_plan_execution_schema import (
    converge_qa_plan_execution_schema,
)


MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0043_scoped_deployment_qa_execution"
)


def _constraint_names(conn, table: str) -> set[str]:
    return {
        str(row[0])
        for row in conn.execute(
            "SELECT conname FROM pg_constraint "
            f"WHERE conrelid='{table}'::regclass AND contype='c'"
        ).fetchall()
    }


def _install_legacy_contract(conn) -> tuple[int, int]:
    conn.execute("DROP TABLE qa_plan_execution_results")
    conn.execute("DROP TABLE qa_plan_executions")
    conn.execute(
        """
        CREATE TABLE qa_plan_executions (
            id TEXT PRIMARY KEY,
            item_id INTEGER,
            deployment_run_id TEXT,
            transition_id TEXT,
            actor_id TEXT,
            session_id TEXT NOT NULL,
            roster_digest TEXT NOT NULL,
            roster_json TEXT NOT NULL,
            cursor_ordinal INTEGER NOT NULL DEFAULT 0,
            state TEXT NOT NULL CHECK(state IN (
                'active','waiting','awaiting_agent_review','completed','aborted','error'
            )),
            machine_lease_id INTEGER,
            created_at TEXT NOT NULL,
            heartbeat_at TEXT NOT NULL,
            completed_at TEXT,
            release_reason TEXT,
            CONSTRAINT qa_plan_executions_check CHECK (
                (item_id IS NOT NULL AND deployment_run_id IS NULL
                    AND transition_id IS NOT NULL) OR
                (item_id IS NULL AND deployment_run_id IS NOT NULL
                    AND transition_id IS NULL)
            ),
            CONSTRAINT qa_plan_executions_subject_check CHECK (
                (item_id IS NOT NULL AND deployment_run_id IS NULL
                    AND transition_id IS NOT NULL) OR
                (item_id IS NULL AND deployment_run_id IS NOT NULL
                    AND transition_id IS NULL)
            )
        )
        """
    )
    conn.execute(
        "CREATE UNIQUE INDEX idx_qa_plan_executions_deployment_active "
        "ON qa_plan_executions(deployment_run_id) "
        "WHERE deployment_run_id IS NOT NULL "
        "AND state IN ('active','waiting','awaiting_agent_review')"
    )
    conn.execute(
        "ALTER TABLE qa_requirements DROP CONSTRAINT qa_requirements_subject_check"
    )
    conn.execute(
        "ALTER TABLE qa_requirements ADD CONSTRAINT qa_requirements_check CHECK ("
        "(item_id IS NOT NULL AND epic_id IS NULL AND task_num IS NULL "
        "AND deployment_run_id IS NULL) OR "
        "(item_id IS NULL AND epic_id IS NOT NULL AND task_num IS NOT NULL "
        "AND deployment_run_id IS NULL) OR "
        "(item_id IS NULL AND epic_id IS NULL AND task_num IS NULL "
        "AND deployment_run_id IS NOT NULL))"
    )
    for index in REQUIREMENT_SCOPE_INDEX_NAMES:
        conn.execute(f'DROP INDEX "{index}"')
    conn.execute(
        "CREATE UNIQUE INDEX idx_qa_requirement_deployment_materialization "
        "ON qa_requirements(deployment_run_id,plan_id,plan_case_key,"
        "COALESCE(host_baseline,'')) "
        "WHERE deployment_run_id IS NOT NULL AND plan_id IS NOT NULL"
    )
    requirement_id = int(
        conn.execute(
            "INSERT INTO qa_requirements("
            "deployment_run_id,qa_kind,qa_phase,created_at"
            ") VALUES ('run-legacy','browser','post_deploy','then') RETURNING id"
        ).fetchone()[0]
    )
    conn.execute(
        "INSERT INTO qa_plan_executions("
        "id,deployment_run_id,session_id,roster_digest,roster_json,state,"
        "created_at,heartbeat_at"
        ") VALUES ('execution-legacy','run-legacy','session','digest','[]',"
        "'awaiting_agent_review','then','then')"
    )
    return requirement_id, 1


def test_cutover_preserves_legacy_waits_results_runs_and_artifacts(test_db) -> None:
    requirement_id, _ = _install_legacy_contract(test_db)

    converge_qa_plan_execution_schema(test_db)
    assert "idx_qa_plan_executions_deployment_active" in {
        str(row[0])
        for row in test_db.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename='qa_plan_executions'"
        ).fetchall()
    }
    assert "qa_plan_executions_check" in _constraint_names(
        test_db, "qa_plan_executions"
    )

    test_db.execute(
        "INSERT INTO qa_plan_execution_results("
        "execution_id,ordinal,requirement_id,result_json,completed_at"
        ") VALUES ('execution-legacy',0,%s,'{}','then')",
        (requirement_id,),
    )
    run_id = int(
        test_db.execute(
            "INSERT INTO qa_runs("
            "qa_requirement_id,performed_by,qa_kind,verdict,created_at"
            ") VALUES (%s,'runner','browser','pass','then') RETURNING id",
            (requirement_id,),
        ).fetchone()[0]
    )
    artifact_id = int(
        test_db.execute(
            "INSERT INTO qa_artifacts(qa_run_id,artifact_type,created_at) "
            "VALUES (%s,'screenshot','then') RETURNING id",
            (run_id,),
        ).fetchone()[0]
    )

    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)
    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)

    assert test_db.execute(
        "SELECT state,deployment_stage,deployment_member_item_id "
        "FROM qa_plan_executions WHERE id='execution-legacy'"
    ).fetchone() == ("awaiting_agent_review", None, None)
    assert (
        test_db.execute(
            "SELECT result_json FROM qa_plan_execution_results "
            "WHERE execution_id='execution-legacy'"
        ).fetchone()["result_json"]
        == "{}"
    )
    assert (
        test_db.execute(
            "SELECT verdict FROM qa_runs WHERE id=%s", (run_id,)
        ).fetchone()["verdict"]
        == "pass"
    )
    assert (
        test_db.execute(
            "SELECT artifact_type FROM qa_artifacts WHERE id=%s", (artifact_id,)
        ).fetchone()["artifact_type"]
        == "screenshot"
    )
    assert "qa_plan_executions_check" not in _constraint_names(
        test_db, "qa_plan_executions"
    )
    assert "qa_requirements_check" not in _constraint_names(test_db, "qa_requirements")
    all_indexes = {
        str(row[0])
        for row in test_db.execute("SELECT indexname FROM pg_indexes").fetchall()
    }
    assert set(EXECUTION_SCOPE_INDEX_NAMES).issubset(all_indexes)
    assert set(REQUIREMENT_SCOPE_INDEX_NAMES).issubset(all_indexes)
    assert "idx_qa_plan_executions_deployment_active" not in all_indexes
    assert "idx_qa_requirement_deployment_materialization" not in all_indexes


def test_fresh_schema_has_exact_scoped_contract_and_serving_floor(test_db) -> None:
    assert_deployment_scope_contract(test_db)
    assert MIGRATION.MINIMUM_SERVING_VERSION == NEXT_RELEASE


def test_invariant_rejects_weaker_regrouping_with_the_same_tokens(test_db) -> None:
    test_db.execute(
        f"ALTER TABLE qa_plan_executions DROP CONSTRAINT "
        f'"{EXECUTION_SUBJECT_CONSTRAINT}"'
    )
    test_db.execute(
        f"ALTER TABLE qa_plan_executions ADD CONSTRAINT "
        f'"{EXECUTION_SUBJECT_CONSTRAINT}" CHECK ('
        f"{LEGACY_EXECUTION_SUBJECT_EXPRESSION} OR ("
        "item_id IS NULL AND deployment_run_id IS NOT NULL "
        "AND transition_id IS NULL AND deployment_stage IS NULL "
        "AND deployment_member_item_id IS NULL) OR ("
        "deployment_stage IS NOT NULL AND TRIM(deployment_stage) <> ''))"
    )

    with pytest.raises(RuntimeError, match="unrecognized subject checks"):
        assert_deployment_scope_contract(test_db)


def test_constraint_comparison_preserves_quoted_literal_contents() -> None:
    assert _canonical_sql("CHECK (state = 'ACTIVE')") != _canonical_sql(
        "CHECK (state = 'active')"
    )
    assert _canonical_sql("CHECK (note = 'a b')") != _canonical_sql(
        "CHECK (note = 'ab')"
    )


def test_scoped_subjects_reject_blank_stage_names(test_db) -> None:
    with pytest.raises(db_backend.integrity_error_types(test_db)):
        test_db.execute(
            "INSERT INTO qa_plan_executions("
            "id,deployment_run_id,deployment_stage,session_id,roster_digest,"
            "roster_json,state,created_at,heartbeat_at"
            ") VALUES ('blank-stage','run-blank','   ','session','digest','[]',"
            "'active','then','then')"
        )
    test_db.rollback()
    with pytest.raises(db_backend.integrity_error_types(test_db)):
        test_db.execute(
            "INSERT INTO qa_requirements("
            "deployment_run_id,deployment_stage,qa_kind,qa_phase,created_at"
            ") VALUES ('run-blank','','browser','post_deploy','then')"
        )
    test_db.rollback()


def test_invariant_rejects_live_index_without_human_review_state(test_db) -> None:
    index = "idx_qa_plan_executions_deployment_stage_active"
    test_db.execute(f'DROP INDEX "{index}"')
    test_db.execute(
        f"CREATE UNIQUE INDEX {index} "
        "ON qa_plan_executions(deployment_run_id,deployment_stage) "
        "WHERE deployment_run_id IS NOT NULL "
        "AND deployment_stage IS NOT NULL "
        "AND deployment_member_item_id IS NULL "
        "AND state IN ('active','waiting')"
    )
    with pytest.raises(AssertionError, match="wrong predicate"):
        assert_deployment_scope_contract(test_db)


def test_invariant_rejects_same_name_non_unique_index(test_db) -> None:
    index = "idx_qa_plan_executions_deployment_stage_active"
    test_db.execute(f'DROP INDEX "{index}"')
    test_db.execute(
        f"CREATE INDEX {index} "
        "ON qa_plan_executions(deployment_run_id,deployment_stage) "
        "WHERE deployment_run_id IS NOT NULL "
        "AND deployment_stage IS NOT NULL "
        "AND deployment_member_item_id IS NULL "
        "AND state IN ('active','awaiting_agent_review','waiting')"
    )
    with pytest.raises(AssertionError, match="must be unique, valid, and ready"):
        assert_deployment_scope_contract(test_db)


def test_invariant_rejects_wider_index_predicate(test_db) -> None:
    index = "idx_qa_plan_executions_deployment_stage_active"
    test_db.execute(f'DROP INDEX "{index}"')
    test_db.execute(
        f"CREATE UNIQUE INDEX {index} "
        "ON qa_plan_executions(deployment_run_id,deployment_stage) "
        "WHERE (deployment_run_id IS NOT NULL "
        "AND deployment_stage IS NOT NULL "
        "AND deployment_member_item_id IS NULL "
        "AND state IN ('active','awaiting_agent_review','waiting')) OR TRUE"
    )
    with pytest.raises(AssertionError, match="wrong predicate"):
        assert_deployment_scope_contract(test_db)


def test_invariant_rejects_legacy_shape_under_current_constraint_name(test_db) -> None:
    test_db.execute(
        f'ALTER TABLE qa_plan_executions DROP CONSTRAINT "{EXECUTION_SUBJECT_CONSTRAINT}"'
    )
    test_db.execute(
        f'ALTER TABLE qa_plan_executions ADD CONSTRAINT "{EXECUTION_SUBJECT_CONSTRAINT}" '
        f"CHECK ({LEGACY_EXECUTION_SUBJECT_EXPRESSION})"
    )
    with pytest.raises(AssertionError, match="does not match"):
        assert_deployment_scope_contract(test_db)


def test_cutover_refuses_unrecognized_subject_check_instead_of_dropping(test_db) -> None:
    _install_legacy_contract(test_db)
    name = "qa_plan_executions_stricter_subject_check"
    test_db.execute(
        f'ALTER TABLE qa_plan_executions ADD CONSTRAINT "{name}" CHECK ('
        f"({LEGACY_EXECUTION_SUBJECT_EXPRESSION}) AND session_id IS NOT NULL)"
    )
    with pytest.raises(RuntimeError, match="unrecognized subject checks"):
        MIGRATION.apply(test_db)
    assert name in _constraint_names(test_db, "qa_plan_executions")
