"""A redeploy cannot cut a live Test Machine walk; begin still proves its build."""

import json

import pytest

from runtime.api.domain.machine_qa_host_test_support import (
    TEST_MACHINE_SETTINGS,
    _terminal_recipe,
    configure_test_machine,
)
from runtime.api.domain.qa_requirement_target_rebind_test_support import _hosted_prod_pair
from yoke_contracts.timestamps import utc_now
from yoke_core.domain import served_revision_probe as probe
from yoke_core.domain.machine_qa_operation_lease import finish_operation_execution
from yoke_core.domain.qa_plan_execution_lifecycle import heartbeat_plan_execution
from yoke_core.domain.qa_plan_management import create_plan, replace_plan_cases
from yoke_core.domain.qa_run_verdict_record import insert_qa_run
from yoke_core.domain.qa_standalone_execution import begin_standalone_execution

SHA = "a" * 40
OTHER = "b" * 40
MACHINE = TEST_MACHINE_SETTINGS["resource_name"]
SESSION = "manual-owner"


def _serve(monkeypatch, sha, calls=None):
    def fetch(url):
        if calls is not None:
            calls.append(url)
        return probe.ServedRevisionRead(status=200, body=sha)

    monkeypatch.setattr(probe, "fetch_served_revision", fetch)


@pytest.fixture
def walk(test_db, tmp_path, monkeypatch):
    configure_test_machine(test_db, tmp_path, monkeypatch)
    owner, _ = _hosted_prod_pair(test_db)
    test_db.execute(
        "UPDATE environments SET name='stage', settings=jsonb_set(settings::jsonb, "
        "'{qa,identity_path}', '\"/served-build\"'::jsonb)::text WHERE id=%s",
        (owner,),
    )
    plan = create_plan(test_db, project="yoke", slug="machine-walk", target_environment=str(owner))
    replace_plan_cases(test_db, plan_id=plan["id"], cases=[{
        "case_key": "host-check", "method_id": "terminal-check",
        "instructions": "Run a host check.", "expected_outcome": "The check passes.",
        "method_config": {**_terminal_recipe(), "test_machine": MACHINE},
        "entry_surface": "printf done", "required_completion": "complete",
        "host_baselines": ["fresh-host"],
    }])
    test_db.commit()
    monkeypatch.setenv("YOKE_ENVIRONMENT", "prod")
    _serve(monkeypatch, SHA)
    execution = _begin(test_db, tmp_path)
    assert execution["served_build_sha"] == SHA
    return execution


def _begin(conn, tmp_path, plan="machine-walk"):
    return begin_standalone_execution(
        conn, plan=plan, project="yoke", actor_id="7", session_id=SESSION,
        test_machine=MACHINE, source_revision=SHA, checkout_path=str(tmp_path),
    )


def test_heartbeat_and_host_operation_survive_a_redeploy(test_db, monkeypatch, walk):
    calls = []
    _serve(monkeypatch, OTHER, calls)
    heartbeat_plan_execution(test_db, walk)
    assert finish_operation_execution(
        test_db, None, mission=walk, reason="done", contract_digest="mission-operation",
    ) is False
    assert calls == []


def test_owner_resumes_a_live_machine_walk_after_a_redeploy(test_db, tmp_path, monkeypatch, walk):
    _serve(monkeypatch, OTHER)
    resumed = _begin(test_db, tmp_path)
    assert resumed["id"] == walk["id"]
    assert resumed["served_build_sha"] == SHA


def test_machine_only_result_records_both_shas(test_db, monkeypatch, walk):
    _serve(monkeypatch, OTHER)
    written = insert_qa_run(
        test_db, qa_requirement_id=walk["roster"][0]["requirement_id"],
        qa_kind="terminal-check", performed_by="7", created_at=utc_now(), verdict="pass",
    )
    row = test_db.execute(
        "SELECT served_build_sha,served_build_status,raw_result FROM qa_runs WHERE id=%s",
        (written.run_id,),
    ).fetchone()
    assert tuple(row[:2]) == (OTHER, "served_build_changed")
    assert json.loads(row[2])["served_build_changed"] == {"began_sha": SHA, "served_sha": OTHER}

