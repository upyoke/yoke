"""Environment QA records the owner's live build on the control plane."""

import pytest

from runtime.api.domain.qa_requirement_target_rebind_test_support import _hosted_prod_pair
from yoke_core.domain import served_revision_probe as probe
from yoke_core.domain.qa_environment_served_build import observe_build
from yoke_core.domain.qa_execution_environment_target import (
    QaExecutionTargetError, resolve_plan_execution_target,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_standalone_execution import begin_standalone_execution
from yoke_core.domain.qa_run_verdict_record import insert_qa_run, update_qa_run

SHA = "a" * 40
OTHER = "b" * 40


def _setup(conn, monkeypatch, *, path=True):
    owner, _ = _hosted_prod_pair(conn)
    conn.execute("UPDATE environments SET name='stage' WHERE id=%s", (owner,))
    if path:
        conn.execute(
            "UPDATE environments SET settings=jsonb_set(settings::jsonb, "
            "'{qa,identity_path}', '\"/served-build\"'::jsonb)::text WHERE id=%s",
            (owner,),
        )
    plan = create_plan(conn, project="yoke", slug="remote-proof", target_environment=str(owner))
    replace_plan_cases(conn, plan_id=plan["id"], cases=[{
        "case_key": "observed", "method_id": "command",
        "instructions": "Observe the target", "expected_outcome": "Build matches",
        "method_config": {"command": "true"},
    }])
    conn.commit()
    monkeypatch.setenv("YOKE_ENVIRONMENT", "prod")
    urls = []
    def fetch(url):
        urls.append(url)
        return probe.ServedRevisionRead(status=200, body=SHA)
    monkeypatch.setattr(probe, "fetch_served_revision", fetch)
    return owner, plan, urls


def _begin(conn):
    return begin_standalone_execution(
        conn, plan="remote-proof", project="yoke", actor_id="7", session_id="manual-owner",
        source_revision=SHA, checkout_path="/tmp/manual-proof",
    )


def test_bridge_probes_owner_by_id_and_records_begin_and_result(test_db, monkeypatch):
    owner, _, urls = _setup(test_db, monkeypatch)
    execution = _begin(test_db)
    assert execution["served_build_sha"] == SHA
    assert execution["execution_target"]["environment"] == {"id": owner, "name": "stage"}
    requirement = execution["roster"][0]["requirement_id"]
    written = insert_qa_run(test_db, qa_requirement_id=requirement, qa_kind="command")
    update_qa_run(test_db, written.run_id, {"verdict": "pass"})
    row = test_db.execute("SELECT served_build_sha,served_build_status FROM qa_runs WHERE id=%s", (written.run_id,)).fetchone()
    assert tuple(row) == (SHA, "observed")
    assert urls == ["https://api.upyoke.com/served-build"] * 3


def test_changed_build_refuses_result_and_preserves_unjudged_run(test_db, monkeypatch):
    _setup(test_db, monkeypatch)
    execution = _begin(test_db)
    requirement = execution["roster"][0]["requirement_id"]
    written = insert_qa_run(test_db, qa_requirement_id=requirement, qa_kind="command")
    monkeypatch.setattr(probe, "fetch_served_revision", lambda _: probe.ServedRevisionRead(status=200, body=OTHER))
    with pytest.raises(QaExecutionTargetError, match=f"served_build_changed: began on {SHA}; now serves {OTHER}"):
        update_qa_run(test_db, written.run_id, {"verdict": "pass"})
    assert test_db.execute("SELECT verdict FROM qa_runs WHERE id=%s", (written.run_id,)).fetchone()[0] is None


@pytest.mark.parametrize("read", [probe.ServedRevisionRead(error="offline"), probe.ServedRevisionRead(status=200, body="unknown")])
def test_unanswerable_build_refuses_before_begin(test_db, monkeypatch, read):
    _setup(test_db, monkeypatch)
    monkeypatch.setattr(probe, "fetch_served_revision", lambda _: read)
    with pytest.raises(QaExecutionTargetError, match="served_build_unobservable"):
        _begin(test_db)
    assert test_db.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0] == 0


def test_frozen_target_authorization_is_rechecked(test_db, monkeypatch):
    owner, plan, _ = _setup(test_db, monkeypatch)
    target = resolve_plan_execution_target(test_db, plan_id=plan["id"])
    test_db.execute("UPDATE environments SET settings='{}' WHERE id=%s", (owner,))
    with pytest.raises(QaExecutionTargetError, match="not authorized"):
        observe_build(test_db, target)


def test_cross_org_target_refuses_even_with_bridge(test_db, monkeypatch):
    owner, plan, _ = _setup(test_db, monkeypatch)
    test_db.execute("INSERT INTO organizations(id,slug,name,created_at) VALUES (99,'other','Other','2026-01-01T00:00:00Z')")
    test_db.execute("UPDATE projects SET org_id=99 WHERE id=3")
    with pytest.raises(QaExecutionTargetError, match="not authorized"):
        resolve_plan_execution_target(test_db, plan_id=plan["id"])


def test_no_declared_path_is_durable(test_db, monkeypatch):
    _setup(test_db, monkeypatch, path=False)
    execution = _begin(test_db)
    assert execution["served_build_sha"] is None
    assert execution["served_build_status"] == "no_declared_path"
    written = insert_qa_run(test_db, qa_requirement_id=execution["roster"][0]["requirement_id"], qa_kind="command", verdict="pass")
    row = test_db.execute("SELECT served_build_sha,served_build_status FROM qa_runs WHERE id=%s", (written.run_id,)).fetchone()
    assert tuple(row) == (None, "no_declared_path")
