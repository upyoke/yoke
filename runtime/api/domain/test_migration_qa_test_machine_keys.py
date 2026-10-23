"""The history entry names every stored QA host a test machine, repeatably."""

from __future__ import annotations

import importlib
import json

from runtime.api.domain import test_qa_member_machine_partitions as support
from yoke_core.domain.migration_serving_version import NEXT_RELEASE
from yoke_core.domain.qa_plan_execution_state import lock_plan_execution
from yoke_core.domain.qa_plan_execution_store import canonical, roster_digest
from yoke_core.domain.qa_plan_host_leases import execution_host_leases

MIGRATION = importlib.import_module(
    "yoke_core.domain.migrations.0090_qa_test_machine_keys"
)
DOCUMENTS = importlib.import_module(
    "yoke_core.domain.migrations._qa_test_machine_documents"
)
LEGACY_WAITS = """
DROP TABLE qa_host_waits;
CREATE TABLE qa_host_waits (
    id TEXT PRIMARY KEY,
    machine_id TEXT NOT NULL,
    session_id TEXT NOT NULL,
    actor_id INTEGER NOT NULL,
    queued_at TIMESTAMPTZ NOT NULL,
    qa_plan_execution_id TEXT REFERENCES qa_plan_executions(id),
    state TEXT NOT NULL CHECK(state IN ('waiting','reserved','granted','cancelled')),
    claim_id INTEGER REFERENCES work_claims(id),
    resume_command TEXT NOT NULL,
    rationale TEXT NOT NULL DEFAULT '',
    settled_at TIMESTAMPTZ
);
CREATE UNIQUE INDEX idx_qa_host_waits_live_session
    ON qa_host_waits(machine_id, session_id)
    WHERE state IN ('waiting','reserved');
CREATE INDEX idx_qa_host_waits_line
    ON qa_host_waits(machine_id, state, queued_at);
"""


def _retired(config: dict) -> dict:
    renamed = {"test_machine": "machine", "test_machines": "machines"}
    return {renamed.get(key, key): value for key, value in config.items()}


def _rows(conn, sql, params=()):
    return [tuple(row) for row in conn.execute(sql, params).fetchall()]


def _seed_retired_shapes(conn, tmp_path, monkeypatch):
    """Store a live two-host execution the way builds before the rename did."""
    support._seed(
        conn, tmp_path, monkeypatch, simultaneous=True, driver=support.MACHINES[1]
    )
    execution = support._begin(conn)
    assert support._case_begin(execution).primary_success
    current = {
        "cases": _rows(conn, "SELECT id, method_config FROM qa_plan_cases"),
        "requirements": _rows(
            conn, "SELECT id, method_config FROM qa_requirements ORDER BY id"
        ),
        "roster": _rows(
            conn,
            "SELECT roster_json, roster_digest FROM qa_plan_executions WHERE id=%s",
            (execution["id"],),
        )[0],
        "lease": _rows(
            conn,
            "SELECT test_machine_lease_id FROM qa_plan_executions WHERE id=%s",
            (execution["id"],),
        )[0],
    }
    assert current["lease"][0] is not None
    conn.execute(
        "ALTER TABLE qa_plan_executions RENAME COLUMN test_machine_lease_id "
        "TO machine_lease_id"
    )
    for table in ("qa_plan_cases", "qa_requirements"):
        for row_id, raw in _rows(conn, f"SELECT id, method_config FROM {table}"):
            conn.execute(
                f"UPDATE {table} SET method_config=%s WHERE id=%s",
                (canonical(_retired(json.loads(raw))), row_id),
            )
    roster = [
        {**case, "method_config": _retired(case["method_config"])}
        for case in json.loads(current["roster"][0])
    ]
    conn.execute(
        "UPDATE qa_plan_executions SET roster_json=%s, roster_digest=%s WHERE id=%s",
        (canonical(roster), roster_digest(roster), execution["id"]),
    )
    conn.execute(
        "UPDATE work_claims SET scope='{\"machine_id\":\"' || "
        "(scope::jsonb->>'test_machine') || '\"}' WHERE target_kind='qa_admission'"
    )
    requirement_id, config = current["requirements"][0]
    run_id = conn.execute(
        "INSERT INTO qa_runs(qa_requirement_id,performed_by,qa_kind,verdict,"
        "raw_result,started_at,completed_at,created_at) VALUES "
        "(%s,'host_control','plan_case','pass',%s,now(),now(),now()) RETURNING id",
        (
            requirement_id,
            canonical(
                {
                    "method_config": _retired(json.loads(config)),
                    "evidence": {
                        "runner_id": "host_control",
                        "machine": support.MACHINES[1],
                        "note": "keep\u0000me",
                    },
                }
            ),
        ),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO qa_artifacts(qa_run_id,artifact_type,content_type,"
        "artifact_handle,metadata,created_at) VALUES "
        "(%s,'machine_evidence','application/json','{}',%s,now())",
        (run_id, json.dumps({"case_key": "c", "machine": support.MACHINES[1]})),
    )
    conn.execute(LEGACY_WAITS)
    conn.execute(
        "INSERT INTO qa_host_waits(id,machine_id,session_id,actor_id,queued_at,"
        "state,resume_command) VALUES('wait-1',%s,%s,1,now(),'waiting','resume')",
        (support.MACHINES[0], support.SESSION),
    )
    return execution, current, run_id


def test_entry_restores_current_keys_and_the_verified_roster_digest(
    test_db, tmp_path, monkeypatch
):
    execution, current, run_id = _seed_retired_shapes(test_db, tmp_path, monkeypatch)

    MIGRATION.apply(test_db)
    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)

    assert _rows(test_db, "SELECT id, method_config FROM qa_plan_cases") == (
        current["cases"]
    )
    assert _rows(
        test_db, "SELECT id, method_config FROM qa_requirements ORDER BY id"
    ) == current["requirements"]
    assert _rows(
        test_db,
        "SELECT roster_json, roster_digest FROM qa_plan_executions WHERE id=%s",
        (execution["id"],),
    )[0] == current["roster"]
    assert _rows(
        test_db,
        "SELECT test_machine_lease_id FROM qa_plan_executions WHERE id=%s",
        (execution["id"],),
    )[0] == current["lease"]
    locked = lock_plan_execution(test_db, execution["id"])
    assert {lease.target.test_machine for lease in execution_host_leases(
        test_db, locked
    )} == set(support.MACHINES)
    raw = json.loads(
        test_db.execute(
            "SELECT raw_result FROM qa_runs WHERE id=%s", (run_id,)
        ).fetchone()[0]
    )
    assert raw["method_config"] == json.loads(current["requirements"][0][1])
    assert raw["evidence"]["test_machine"] == support.MACHINES[1]
    assert "machine" not in raw["evidence"]
    assert raw["evidence"]["note"] == "keep\u0000me"
    assert _rows(
        test_db,
        "SELECT t.tgenabled FROM pg_trigger t JOIN pg_class c ON c.oid=t.tgrelid "
        "WHERE c.relname='qa_runs' AND t.tgname='qa_runs_verdict_immutable'",
    ) == [("O",)]
    metadata = test_db.execute(
        "SELECT metadata FROM qa_artifacts WHERE qa_run_id=%s", (run_id,)
    ).fetchone()[0]
    assert json.loads(metadata) == {"case_key": "c", "test_machine": support.MACHINES[1]}
    assert _rows(test_db, "SELECT id, test_machine FROM qa_host_waits") == [
        ("wait-1", support.MACHINES[0])
    ]
    indexes = dict(
        _rows(
            test_db,
            "SELECT indexname, indexdef FROM pg_indexes "
            "WHERE tablename='qa_host_waits' AND indexname LIKE 'idx_qa_host_waits_%%'",
        )
    )
    assert set(indexes) == {
        "idx_qa_host_waits_live_session",
        "idx_qa_host_waits_line",
    }
    assert all("test_machine" in definition for definition in indexes.values())
    scopes = _rows(
        test_db,
        "SELECT scope FROM work_claims WHERE target_kind='qa_admission' ORDER BY id",
    )
    assert scopes and all(
        set(json.loads(scope)) == {"test_machine"} for (scope,) in scopes
    )


def test_a_document_already_carrying_the_current_key_keeps_it():
    folded = DOCUMENTS.fold_method_config(
        {"machine": "old-lab", "test_machine": "new-lab", "machines": ["a", "b"]}
    )
    assert folded == {"test_machine": "new-lab", "test_machines": ["a", "b"]}
    current = {"test_machine": "new-lab"}
    assert DOCUMENTS.fold_method_config(current) is current


def test_evidence_from_other_runners_and_unnamed_metadata_are_left_alone():
    other = {"evidence": {"runner_id": "worktree_run", "machine": "runner-host"}}
    assert DOCUMENTS.fold_run_result(other) == other
    nested = {"machine": {"kind": "fixture"}}
    assert DOCUMENTS.fold_artifact_metadata(nested) == nested


def test_entry_declares_the_next_release_serving_floor():
    assert MIGRATION.MINIMUM_SERVING_VERSION == NEXT_RELEASE


def test_a_retired_lease_column_beside_the_current_one_is_dropped(test_db):
    test_db.execute("ALTER TABLE qa_plan_executions ADD COLUMN machine_lease_id INTEGER")
    assert MIGRATION._column_exists(test_db, "qa_plan_executions", "machine_lease_id")

    MIGRATION.apply(test_db)
    MIGRATION.invariants(test_db)

    assert not MIGRATION._column_exists(
        test_db, "qa_plan_executions", "machine_lease_id"
    )
