"""Failed preparation preserves safe diagnostics and the last proven baseline."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from yoke_contracts.machine_qa_failures import HostControlLocalError
from yoke_core.domain import machine_qa_local_execution as local
from yoke_core.domain import machine_qa_plan_case_execution as client
from yoke_harness import qa_host_package_fixture
from yoke_harness.qa_host_package_fixture import restore_host_packages


@pytest.fixture
def mission(monkeypatch):
    contract = SimpleNamespace(
        baselines=["fresh-host"],
        continues_execution_id=None,
        cases=[SimpleNamespace(host_baseline="fresh-host", method_config={})],
        plan_execution_id="diagnostic-mission",
        lease_id=7,
        contract_digest="digest",
    )
    baseline = SimpleNamespace(
        name="fresh-host", ok=True, error_code=None, evidence={"restore_proved": True}
    )
    execution = SimpleNamespace(
        control=SimpleNamespace(),
        material=SimpleNamespace(secrets={"credential": "private-token"}),
        reach_baseline=lambda name: baseline,
    )
    monkeypatch.setattr(local, "_mission_contract", lambda raw: contract)
    monkeypatch.setattr(local, "_execution", lambda *args, **kwargs: execution)
    monkeypatch.setattr(
        local, "create_mission_scratch", lambda *args, **kwargs: "/tmp/scratch"
    )
    monkeypatch.setattr(
        qa_host_package_fixture, "restore_host_packages", lambda *args, **kwargs: {}
    )
    return contract, execution, baseline


@pytest.mark.parametrize(
    "phase,state",
    [("heartbeat", "not_started"), ("baseline", "started"), ("scratch", "completed")],
)
def test_failure_preserves_baseline_progress_and_redacts_cause(
    mission, monkeypatch, phase, state
):
    _, execution, _ = mission

    def fail(*args, **kwargs):
        raise RuntimeError("permission denied private-token " + "x" * 900)

    callback = fail if phase == "heartbeat" else None
    if phase == "baseline":
        execution.reach_baseline = fail
    elif phase == "scratch":
        monkeypatch.setattr(local, "create_mission_scratch", fail)
    payload = local.prepare_agent_mission_contract({}, progress_callback=callback)
    preparation = payload["preparation"]
    evidence = preparation["evidence"]
    assert preparation["ok"] is False
    assert evidence["baseline_outcome"]["state"] == state
    receipt = evidence["baseline_outcome"]["receipt"]
    assert (receipt is not None) == (state == "completed")
    assert evidence["scratch_created"] is False
    diagnostic = evidence["preparation_failure"]["diagnostic"]
    assert "permission denied [REDACTED]" in diagnostic
    assert len(diagnostic) <= 512
    assert "private-token" not in json.dumps(payload)
    assert evidence["preparation_failure"]["recovery"]


def test_package_failure_keeps_output_and_completed_baseline(mission, monkeypatch):
    _, execution, _ = mission
    execution.control.os = "linux"
    execution.control.golden_baseline_path = "/var/lib/golden"
    execution.control.run_command = lambda *args, **kwargs: subprocess.CompletedProcess(
        args=[],
        returncode=100,
        stdout=json.dumps(
            {
                "ok": False,
                "apt_failure": {
                    "operation": "purge",
                    "packages": ["xdotool"],
                    "exit_code": 100,
                    "stdout": "package output private-token",
                    "stderr": "E: package removal refused private-token",
                },
            }
        ),
        stderr="SSH transport notice",
    )
    monkeypatch.setattr(
        qa_host_package_fixture, "restore_host_packages", restore_host_packages
    )
    payload = local.prepare_agent_mission_contract({})
    preparation = payload["preparation"]
    failure = preparation["evidence"]["preparation_failure"]
    assert preparation["error_code"] == "os_package_fixture_failed"
    assert failure["phase"] == "os_packages"
    assert failure["exit_code"] == 100
    assert 'operation=purge packages=["xdotool"]' in failure["diagnostic"]
    assert failure["stdout"] == "package output [REDACTED]"
    assert "package removal refused [REDACTED]" in failure["stderr"]
    assert "private-token" not in json.dumps(payload)
    outcome = preparation["evidence"]["baseline_outcome"]
    assert outcome["state"] == "completed"
    assert outcome["receipt"]["evidence"] == {"restore_proved": True}


def test_typed_materialization_failure_records_unstarted_baseline(mission, monkeypatch):
    def fail(*args, **kwargs):
        raise HostControlLocalError(
            code="host_control_credential_missing",
            phase="credential_materialization",
            detail="SSH credential is unavailable",
            recovery_hint="Configure the executing machine credential.",
        )

    monkeypatch.setattr(local, "_execution", fail)
    preparation = local.prepare_agent_mission_contract({})["preparation"]
    assert preparation["error_code"] == "host_control_credential_missing"
    assert preparation["evidence"]["baseline_outcome"]["state"] == "not_started"
    assert (
        "SSH credential is unavailable"
        in preparation["evidence"]["preparation_failure"]["diagnostic"]
    )


def test_failed_baseline_receipt_is_retained_without_later_host_operations(
    mission, monkeypatch
):
    _, _, baseline = mission
    baseline.ok = False
    baseline.error_code = "baseline_verification_failed"
    monkeypatch.setattr(
        local,
        "create_mission_scratch",
        lambda *args, **kwargs: pytest.fail("scratch after failed baseline"),
    )
    preparation = local.prepare_agent_mission_contract({})["preparation"]
    outcome = preparation["evidence"]["baseline_outcome"]
    assert outcome["state"] == "started"
    assert outcome["receipt"]["error_code"] == "baseline_verification_failed"
    assert preparation["error_code"] == "baseline_verification_failed"


def test_local_capture_stops_even_when_serving_build_returns_unjudged_docket(
    mission, monkeypatch
):
    def fail(*args, **kwargs):
        raise RuntimeError("scratch write denied")

    monkeypatch.setattr(local, "create_mission_scratch", fail)
    calls = []

    def dispatch(function_id, **kwargs):
        calls.append(function_id)
        if function_id == "test_machine.plan_case.begin":
            return {"state": "ready", "execution": {}}
        if function_id == "qa.plan_execution.heartbeat":
            return {}
        preparation = kwargs["payload"]["preparation"]
        assert preparation["ok"] is False
        return {
            "result": {
                "requirement_id": 15,
                "run_id": 23,
                "case_outcome": "needs_review",
                "preparation": preparation,
            }
        }

    monkeypatch.setattr(client, "_dispatch", dispatch)
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_host_control.register_test_machine_host_control",
        lambda: None,
    )
    result = client.execute_plan_agent_mission_case(
        {"requirement_id": 15, "item_id": 11},
        execution_id="diagnostic-mission",
        ordinal=0,
        actor=None,
    )
    assert result["verdict"] == "error"
    assert result["case_outcome"] == "blocked_on_precondition"
    assert result["run_id"] == 23
    assert "scratch write denied" in result["error"]
    assert calls[-1] == "test_machine.mission.ready"


@pytest.mark.parametrize("failed", [False, True])
def test_delivery_evidence_accepts_the_holders_new_deployed_preparation(
    mission, monkeypatch, failed
):
    from ops.qa import mission_preparation_evidence as reader

    if failed:

        def refuse(*args, **kwargs):
            raise RuntimeError("scratch unavailable")

        monkeypatch.setattr(local, "create_mission_scratch", refuse)
    preparation = local.prepare_agent_mission_contract({})["preparation"]
    captured = "2026-10-02T15:01:00Z"
    proof_run_id = "current-delivery"
    binding = {
        "deployment_run_id": "current-delivery",
        "deployment_stage": "item-qa",
        "execution_candidate_revision": "deployed-candidate",
        "plan_id": 17,
        "plan_case_key": "holder-case",
    }
    monkeypatch.setenv("DEPLOYMENT_RUN_ID", "current-delivery")
    monkeypatch.setenv("DEPLOYMENT_MEMBER_REF", "member")
    monkeypatch.setenv("BASE_URL", "https://deployed.example")

    def read(*args):
        if args[:2] == ("deployment-runs", "get"):
            assert args == ("deployment-runs", "get", "current-delivery")
            return {
                "run": {
                    "current_stage": "item-qa",
                    "release_lineage": "deployed-candidate",
                }
            }
        if args[:3] == ("qa", "plan", "get"):
            return {
                "plan": {
                    "id": 17,
                    "execution_target": {
                        "endpoints": {"api_url": "https://deployed.example"}
                    },
                    "cases": [
                        {
                            "case_key": "holder-case",
                            "proofs": [
                                {
                                    "deployment_run_id": proof_run_id,
                                    "happened_at": captured,
                                    "run_id": 91,
                                }
                            ],
                        }
                    ],
                }
            }
        if args[:3] == ("qa", "requirement", "get"):
            return {"requirement": binding}
        return {
            "run": {
                "qa_requirement_id": 29,
                "raw_result": json.dumps({"preparation": preparation}),
            }
        }

    monkeypatch.setattr(reader, "_read", read)
    args = SimpleNamespace(
        stage="item-qa",
        holder_plan="holder-plan",
        project="project",
        case_key="holder-case",
        require_package_restore=False,
    )
    result = reader.verify(args)
    assert result["holder_qa_run_id"] == 91
    assert result["preparation"]["ok"] is not failed
    args.require_package_restore = True
    with pytest.raises(ValueError, match="os_package_restore_unproved"):
        reader.verify(args)
    preparation["evidence"]["os_packages"] = {"ok": False}
    with pytest.raises(ValueError, match="os_package_restore_unproved"):
        reader.verify(args)
    preparation["evidence"]["os_packages"] = {"ok": True}
    assert reader.verify(args)["preparation"]["evidence"]["os_packages"]["ok"]
    for field in (
        "deployment_run_id",
        "deployment_stage",
        "execution_candidate_revision",
    ):
        saved = binding[field]
        binding[field] = "another-subject"
        with pytest.raises(ValueError, match="this deployment stage and candidate"):
            reader.verify(args)
        binding[field] = saved
    proof_run_id = "older-delivery"
    with pytest.raises(ValueError, match="Ask the holder to execute"):
        reader.verify(args)
