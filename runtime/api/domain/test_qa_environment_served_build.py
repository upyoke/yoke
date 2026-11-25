"""Environment QA records the owner's live build on the control plane."""

import json

import pytest

from runtime.api.domain.qa_requirement_target_rebind_test_support import _hosted_prod_pair
from runtime.api.fixtures.backlog_inserts import insert_item, insert_qa_requirement
from yoke_core.domain import served_revision_probe as probe
from yoke_core.domain.qa_environment_served_build import observe_build
from yoke_core.domain.qa_execution_environment_target import (
    QaExecutionTargetError, resolve_plan_execution_target,
)
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_standalone_execution import begin_standalone_execution
from yoke_core.domain.qa_run_verdict_record import insert_qa_run, update_qa_run
from yoke_contracts.timestamps import utc_now

SHA = "a" * 40
OTHER = "b" * 40


def _setup(conn, monkeypatch, *, path=True, cases=1):
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
        "case_key": f"observed-{index}", "method_id": "command",
        "instructions": "Observe the target", "expected_outcome": "Build matches",
        "method_config": {"command": "true"},
    } for index in range(cases)])
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
    written = insert_qa_run(test_db, qa_requirement_id=requirement, qa_kind="command", performed_by="7", created_at=utc_now())
    update_qa_run(test_db, written.run_id, {"verdict": "pass"})
    row = test_db.execute("SELECT served_build_sha,served_build_status FROM qa_runs WHERE id=%s", (written.run_id,)).fetchone()
    assert tuple(row) == (SHA, "observed")
    assert urls == ["https://api.upyoke.com/served-build"] * 3


def _assert_changed_build_pass(conn, run_id, *, served=OTHER):
    row = conn.execute(
        "SELECT verdict,served_build_sha,served_build_status,raw_result FROM qa_runs WHERE id=%s",
        (run_id,),
    ).fetchone()
    assert tuple(row[:3]) == ("pass", served, "served_build_changed")
    assert json.loads(row[3])["served_build_changed"] == {"began_sha": SHA, "served_sha": served}


def test_changed_build_records_pass_on_completion(test_db, monkeypatch):
    _setup(test_db, monkeypatch)
    execution = _begin(test_db)
    requirement = execution["roster"][0]["requirement_id"]
    written = insert_qa_run(test_db, qa_requirement_id=requirement, qa_kind="command", performed_by="7", created_at=utc_now())
    monkeypatch.setattr(probe, "fetch_served_revision", lambda _: probe.ServedRevisionRead(status=200, body=OTHER))
    update_qa_run(test_db, written.run_id, {"verdict": "pass"})
    _assert_changed_build_pass(test_db, written.run_id)


@pytest.mark.parametrize(
    ("capture_sha", "verdict_sha"), [(None, OTHER), (OTHER, OTHER), (OTHER, "c" * 40), (OTHER, SHA)],
)
def test_build_change_records_pass_without_an_execution(test_db, monkeypatch, capture_sha, verdict_sha):
    _, plan, _ = _setup(test_db, monkeypatch)
    target = resolve_plan_execution_target(test_db, plan_id=plan["id"])
    insert_item(test_db, id=42, title="Remote QA")
    insert_qa_requirement(
        test_db, id=10, item_id=42, target_env="stage",
        execution_target_json=json.dumps(target),
    )
    written = insert_qa_run(
        test_db, qa_requirement_id=10, qa_kind="command", performed_by="7", created_at=utc_now(),
    )
    row = test_db.execute(
        "SELECT served_build_sha,served_build_status FROM qa_runs WHERE id=%s", (written.run_id,),
    ).fetchone()
    assert tuple(row) == (SHA, "observed")
    assert test_db.execute("SELECT COUNT(*) FROM qa_plan_executions").fetchone()[0] == 0

    if capture_sha:
        monkeypatch.setattr(
            probe, "fetch_served_revision",
            lambda _: probe.ServedRevisionRead(status=200, body=capture_sha),
        )
        update_qa_run(test_db, written.run_id, {"execution_status": "captured"})

    monkeypatch.setattr(
        probe, "fetch_served_revision",
        lambda _: probe.ServedRevisionRead(status=200, body=verdict_sha),
    )
    update_qa_run(test_db, written.run_id, {"verdict": "pass"})
    if verdict_sha != SHA:
        _assert_changed_build_pass(test_db, written.run_id, served=verdict_sha)
    else:
        row = test_db.execute(
            "SELECT verdict,served_build_sha,served_build_status,raw_result "
            "FROM qa_runs WHERE id=%s", (written.run_id,),
        ).fetchone()
        assert tuple(row[:3]) == ("pass", SHA, "observed")
        assert "served_build_changed" not in json.loads(row[3])


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
    written = insert_qa_run(test_db, qa_requirement_id=execution["roster"][0]["requirement_id"], qa_kind="command", performed_by="7", created_at=utc_now(), verdict="pass")
    row = test_db.execute("SELECT served_build_sha,served_build_status FROM qa_runs WHERE id=%s", (written.run_id,)).fetchone()
    assert tuple(row) == (None, "no_declared_path")


def test_build_change_before_first_result_records_pass_against_begin(test_db, monkeypatch):
    _setup(test_db, monkeypatch)
    execution = _begin(test_db)
    monkeypatch.setattr(probe, "fetch_served_revision", lambda _: probe.ServedRevisionRead(status=200, body=OTHER))
    written = insert_qa_run(
        test_db, qa_requirement_id=execution["roster"][0]["requirement_id"],
        qa_kind="command", performed_by="7", created_at=utc_now(), verdict="pass",
    )
    _assert_changed_build_pass(test_db, written.run_id)


def test_roster_step_and_case_run_recheck_frozen_authorization(test_db, monkeypatch):
    from yoke_core.domain.qa_case_execution_context import get_case_execution_context
    from yoke_core.domain.qa_plan_execution_lifecycle import heartbeat_plan_execution

    owner, _, _ = _setup(test_db, monkeypatch)
    execution = _begin(test_db)
    test_db.execute("UPDATE environments SET settings='{}' WHERE id=%s", (owner,))
    with pytest.raises(QaExecutionTargetError, match="not authorized"):
        get_case_execution_context(test_db, requirement_id=execution["roster"][0]["requirement_id"])
    with pytest.raises(QaExecutionTargetError, match="not authorized"):
        heartbeat_plan_execution(test_db, execution)


def test_result_uses_the_executions_frozen_target(test_db, monkeypatch):
    _setup(test_db, monkeypatch)
    execution = _begin(test_db)
    requirement = execution["roster"][0]["requirement_id"]
    test_db.execute("UPDATE qa_requirements SET execution_target_json=NULL,execution_target_digest=NULL WHERE id=%s", (requirement,))
    written = insert_qa_run(test_db, qa_requirement_id=requirement, qa_kind="command",
                            performed_by="7", created_at=utc_now(), verdict="pass")
    assert test_db.execute("SELECT served_build_sha FROM qa_runs WHERE id=%s", (written.run_id,)).fetchone()[0] == SHA


@pytest.mark.parametrize("ran_case", [False, True])
def test_owner_resume_preserves_begin_build(test_db, monkeypatch, ran_case):
    from yoke_core.domain.qa_plan_execution_state import advance_plan_execution

    _, _, urls = _setup(test_db, monkeypatch, cases=2)
    execution = _begin(test_db)
    if ran_case:
        advance_plan_execution(
            test_db, execution, ordinal=0, requirement_id=execution["roster"][0]["requirement_id"],
            result={"verdict": "pass"},
        )
        test_db.commit()

    def fetch_after_redeploy(url):
        urls.append(url)
        return probe.ServedRevisionRead(status=200, body=OTHER)

    monkeypatch.setattr(probe, "fetch_served_revision", fetch_after_redeploy)
    urls.clear()
    resumed = _begin(test_db)
    assert resumed["id"] == execution["id"]
    assert resumed["served_build_sha"] == SHA
    assert urls == []
    row = test_db.execute(
        "SELECT served_build_sha,served_build_status FROM qa_plan_executions WHERE id=%s",
        (execution["id"],),
    ).fetchone()
    assert tuple(row) == (SHA, "observed")
