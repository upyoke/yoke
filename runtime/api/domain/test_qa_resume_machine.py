"""Resume teaching retains the host recorded by the case's durable evidence."""

import json
from unittest.mock import Mock

from yoke_core.domain.qa_plan_execution_continuation import continuation_recipe
from yoke_core.domain.qa_resume_machine import correction_machine, execution_machine


def test_wait_recipe_pins_the_waited_host_without_changing_the_subject():
    execution = {
        "id": "walk",
        "deployment_run_id": "run",
        "deployment_stage": "member-qa",
        "roster": [{"project": "example"}],
    }
    command = continuation_recipe(Mock(), execution, machine="linux-lab")
    assert (
        command
        == "yoke qa plan run --deployment-run-id run --project example --stage member-qa --machine linux-lab --continue-mission"
    )
    assert command.removesuffix(" --continue-mission").endswith("--machine linux-lab")


def test_settled_execution_recovers_host_from_its_recorded_runs():
    conn = Mock()
    conn.execute.side_effect = [
        Mock(fetchall=lambda: [{"result_json": json.dumps({"run_id": 12})}]),
        Mock(
            fetchall=lambda: [
                {
                    "id": 12,
                    "raw_result": json.dumps({"evidence": {"machine": "linux-lab"}}),
                }
            ]
        ),
    ]
    assert (
        execution_machine(conn, {"id": "settled", "machine_lease_id": None})
        == "linux-lab"
    )


def test_correction_uses_failed_attempt_host():
    conn = Mock()
    conn.execute.return_value.fetchone.return_value = {
        "raw_result": json.dumps({"evidence": {"machine": "linux-lab"}})
    }
    assert (
        correction_machine(
            conn, [{"requirement_id": 12, "replacement_requirement_id": 13}]
        )
        == "linux-lab"
    )
    assert conn.execute.call_args.args[1] == (12,)


def test_correction_notice_command_preserves_host(monkeypatch):
    from types import SimpleNamespace
    from yoke_core.domain import deployment_qa_correction_notice as notice

    conn = Mock()
    conn.execute.return_value.fetchone.return_value = {"project_id": 1}
    monkeypatch.setattr(
        notice, "resolve_project", lambda *a: SimpleNamespace(slug="example")
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_resume_machine.correction_machine", lambda *a: "linux-lab"
    )
    bodies = []
    monkeypatch.setattr(
        notice,
        "push_run_scoped_notice",
        lambda *a, **k: bodies.append(k["body_for_route"](None)) or "sent",
    )
    result = notice.notify_correction(
        conn,
        result={"deployment_run_id": "run", "deployment_stage": "qa"},
        replacements=[{"requirement_id": 12, "replacement_requirement_id": 13}],
    )
    assert result["delivery"] == "sent"
    assert "--project example --machine linux-lab" in bodies[0]


def test_mission_docket_recovers_released_host_lease(monkeypatch):
    from types import SimpleNamespace
    from yoke_core.domain.qa_resume_machine import run_machine

    monkeypatch.setattr(
        "yoke_core.domain.qa_resume_machine.get_claim",
        lambda conn, lease: SimpleNamespace(
            target=SimpleNamespace(machine_id="linux-lab")
        ),
    )
    assert (
        run_machine(Mock(), json.dumps({"host_control_submission": {"lease_id": 42}}))
        == "linux-lab"
    )


def test_execution_that_never_reached_a_host_has_no_host_to_pin():
    conn = Mock()
    conn.execute.return_value.fetchall.return_value = []
    assert (
        execution_machine(
            conn, {"id": "pre-host", "roster": [{"runner_id": "agent_mission"}]}
        )
        is None
    )
