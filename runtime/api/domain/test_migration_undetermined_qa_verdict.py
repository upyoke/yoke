"""Ordered hard cutover for explainable undetermined QA verdicts."""

from __future__ import annotations

import psycopg
import pytest

from runtime.api.fixtures.backlog_inserts import (
    insert_item,
    insert_qa_requirement,
)
from runtime.api.fixtures.pg_testdb import test_database
from yoke_core.domain import migrations as migration_history_package
from yoke_core.domain.migration_history import (
    history_dir,
    load_migration_module,
    ordered_entries,
)
from yoke_core.domain.migration_serving_version import declared_minimum
from yoke_core.domain.schema_common import _get_check_constraint_defs


ENTRY_NAME = "0014_undetermined_qa_verdict"


def _entry():
    directory = history_dir(migration_history_package)
    record = next(row for row in ordered_entries(directory) if row.name == ENTRY_NAME)
    return load_migration_module(directory / f"{record.name}.py", record.name)


entry = _entry()


def _legacy_verdict_shape(conn) -> int:
    item = insert_item(conn, id=9813, title="Explain uncertain QA evidence")
    requirement = insert_qa_requirement(
        conn,
        item_id=int(item["id"]),
        qa_kind="plan_case",
    )
    entry._drop_verdict_checks(conn, "qa_runs")
    entry._drop_verdict_checks(conn, "qa_plan_review_verdicts")
    conn.execute(
        "ALTER TABLE qa_runs ADD CONSTRAINT qa_runs_verdict_check "
        "CHECK(verdict IN ('pass','fail','inconclusive','error'))"
    )
    conn.execute(
        "ALTER TABLE qa_plan_review_verdicts ADD CONSTRAINT "
        "qa_plan_review_verdicts_verdict_check "
        "CHECK(verdict IN ('pass','fail','inconclusive'))"
    )
    run = conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "created_at) VALUES(%s,'agent','plan_case','inconclusive',"
        "'2026-08-20T00:00:00Z') RETURNING id",
        (int(requirement["id"]),),
    ).fetchone()
    conn.commit()
    return int(run[0])


def test_legacy_verdict_becomes_explainable_without_losing_the_run() -> None:
    with test_database() as conn:
        run_id = _legacy_verdict_shape(conn)

        entry.apply(conn)
        entry.invariants(conn)

        row = conn.execute(
            "SELECT verdict,verdict_reason FROM qa_runs WHERE id=%s",
            (run_id,),
        ).fetchone()
        assert tuple(row) == ("undetermined", entry.LEGACY_REASON)
        assert conn.execute("SELECT COUNT(*) FROM qa_runs").fetchone()[0] == 1


def test_cutover_constraints_and_trigger_are_replay_safe() -> None:
    with test_database() as conn:
        _legacy_verdict_shape(conn)

        entry.apply(conn)
        entry.apply(conn)
        entry.invariants(conn)

        run_checks = " ".join(_get_check_constraint_defs(conn, "qa_runs"))
        review_checks = " ".join(
            _get_check_constraint_defs(conn, "qa_plan_review_verdicts")
        )
        assert "undetermined" in run_checks and "inconclusive" not in run_checks
        assert "verdict_reason" in run_checks
        assert "undetermined" in review_checks
        trigger = conn.execute(
            "SELECT COUNT(*) FROM pg_trigger WHERE tgname=%s AND NOT tgisinternal",
            ("qa_runs_verdict_immutable",),
        ).fetchone()[0]
        assert trigger == 1


def test_cutover_rejects_an_undetermined_run_without_a_reason() -> None:
    with test_database() as conn:
        run_id = _legacy_verdict_shape(conn)
        entry.apply(conn)
        conn.commit()
        requirement_id = conn.execute(
            "SELECT qa_requirement_id FROM qa_runs WHERE id=%s", (run_id,)
        ).fetchone()[0]

        with pytest.raises(psycopg.errors.CheckViolation):
            conn.execute(
                "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,"
                "verdict,created_at) VALUES(%s,'agent','plan_case',"
                "'undetermined','2026-08-20T00:00:01Z')",
                (requirement_id,),
            )


def test_cutover_declares_the_first_compatible_serving_build() -> None:
    assert entry.MINIMUM_SERVING_VERSION == "0.1.1+launch.245"
    assert declared_minimum(entry) == entry.MINIMUM_SERVING_VERSION
