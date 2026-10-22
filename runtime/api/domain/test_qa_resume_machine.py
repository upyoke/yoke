"""Resume teaching retains the host recorded by the case's durable evidence."""

import json
from unittest.mock import Mock
from types import SimpleNamespace

import pytest

from yoke_core.domain.qa_plan_execution_continuation import continuation_recipe
from yoke_core.domain.qa_resume_machine import corrected_case_machine, execution_machine


@pytest.mark.parametrize("hosts", [("linux-lab",), ("linux-lab", "test-mac")])
def test_resume_recipe_never_pins_a_host(hosts):
    execution = {
        "id": "walk",
        "deployment_run_id": "run",
        "deployment_stage": "member-qa",
        "roster": [
            {"project": "example", "method_config": {"machine": host}} for host in hosts
        ],
    }
    command = continuation_recipe(Mock(), execution)
    assert (
        command
        == "yoke qa plan run --deployment-run-id run --project example --stage member-qa --continue-mission"
    )
    assert "--machine" not in command


def test_settled_execution_recovers_host_from_its_recorded_runs(monkeypatch):
    _hosts(monkeypatch)
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
        execution_machine(
            conn, {"id": "settled", "machine_lease_id": None}, _case("linux")
        )
        == "linux-lab"
    )


def test_correction_uses_its_own_failed_attempt_host():
    conn = Mock()
    conn.execute.side_effect = [
        Mock(fetchall=lambda: [{"id": 12}]),
        Mock(
            fetchone=lambda: {
                "raw_result": json.dumps({"evidence": {"machine": "linux-lab"}})
            }
        ),
    ]
    assert corrected_case_machine(conn, 13) == "linux-lab"
    assert conn.execute.call_args.args[1] == (12,)


def test_multi_host_correction_notice_omits_a_global_pin(monkeypatch):
    from types import SimpleNamespace
    from yoke_core.domain import deployment_qa_correction_notice as notice

    conn = Mock()
    conn.execute.return_value.fetchone.return_value = {"project_id": 1}
    monkeypatch.setattr(
        notice, "resolve_project", lambda *a: SimpleNamespace(slug="example")
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
        replacements=[
            {"requirement_id": 12, "replacement_requirement_id": 13},
            {"requirement_id": 14, "replacement_requirement_id": 15},
        ],
    )
    assert result["delivery"] == "sent"
    assert "--project example" in bodies[0]
    assert "--machine" not in bodies[0]


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


def test_execution_that_never_reached_a_host_has_no_host_to_pin(monkeypatch):
    _hosts(monkeypatch)
    conn = Mock()
    conn.execute.return_value.fetchall.return_value = []
    assert (
        execution_machine(
            conn,
            {"id": "pre-host", "roster": [{"runner_id": "agent_mission"}]},
            _case("linux"),
        )
        is None
    )


def _case(platform):
    return {"project_id": 1, "method_config": {"os": platform}}


def _hosts(monkeypatch):
    monkeypatch.setattr(
        "yoke_core.domain.machine_qa_capability_rows.test_machine_capability_rows",
        lambda *a, **k: [
            SimpleNamespace(machine=name, settings={"os": platform})
            for name, platform in [("linux-lab", "linux"), ("test-mac", "macos")]
        ],
    )


@pytest.mark.parametrize(
    "platform,expected",
    [("linux", "linux-lab"), ("macos", "test-mac"), ("windows", None)],
)
def test_each_platform_recovers_only_its_own_execution_host(
    monkeypatch, platform, expected
):
    _hosts(monkeypatch)
    conn = Mock()
    conn.execute.side_effect = [
        Mock(
            fetchall=lambda: [
                {"result_json": json.dumps({"run_id": n})} for n in [2, 1]
            ]
        ),
        Mock(
            fetchall=lambda: [
                {"id": n, "raw_result": json.dumps({"evidence": {"machine": host}})}
                for n, host in [(1, "linux-lab"), (2, "test-mac")]
            ]
        ),
    ]
    assert execution_machine(conn, {"id": "multi-host"}, _case(platform)) == expected


def test_single_host_resume_recovers_custody_without_querying_runs(monkeypatch):
    _hosts(monkeypatch)
    monkeypatch.setattr(
        "yoke_core.domain.qa_resume_machine.get_claim",
        lambda *a: SimpleNamespace(target=SimpleNamespace(machine_id="linux-lab")),
    )
    conn = Mock()
    assert (
        execution_machine(
            conn, {"id": "single", "machine_lease_id": 42}, _case("linux")
        )
        == "linux-lab"
    )
    conn.execute.assert_not_called()


def test_stale_continuation_recovers_its_source_platform_host(monkeypatch):
    _hosts(monkeypatch)
    monkeypatch.setattr(
        "yoke_core.domain.qa_resume_machine.get_claim",
        lambda *a: SimpleNamespace(target=SimpleNamespace(machine_id="test-mac")),
    )
    monkeypatch.setattr(
        "yoke_core.domain.qa_plan_execution_store.select_plan_execution",
        lambda *a, **k: {"id": "source", "machine_lease_id": 42},
    )
    conn = Mock()
    conn.execute.return_value.fetchall.return_value = []
    assert (
        execution_machine(
            conn, {"id": "new", "continues_execution_id": "source"}, _case("macos")
        )
        == "test-mac"
    )


@pytest.mark.parametrize("requirement,host", [(13, "linux-lab"), (15, "test-mac")])
def test_corrected_roster_cases_recover_separate_hosts(requirement, host):
    conn = Mock()
    conn.execute.side_effect = [
        Mock(fetchall=lambda: [{"id": requirement - 1}]),
        Mock(
            fetchone=lambda: {"raw_result": json.dumps({"evidence": {"machine": host}})}
        ),
    ]
    assert corrected_case_machine(conn, requirement) == host


def test_correction_without_attempt_follows_its_original_failed_case():
    conn = Mock()
    conn.execute.side_effect = [
        Mock(fetchall=lambda: [{"id": 13}]),
        Mock(fetchone=lambda: None),
        Mock(fetchall=lambda: [{"id": 12}]),
        Mock(
            fetchone=lambda: {
                "raw_result": json.dumps({"evidence": {"machine": "linux-lab"}})
            }
        ),
    ]
    assert corrected_case_machine(conn, 14) == "linux-lab"


def test_recorded_host_removal_refuses_instead_of_substituting_another_host(
    monkeypatch,
):
    _hosts(monkeypatch)
    monkeypatch.setattr(
        "yoke_core.domain.qa_resume_machine.get_claim",
        lambda *a: SimpleNamespace(target=SimpleNamespace(machine_id="removed-lab")),
    )
    with pytest.raises(ValueError, match="qa_resume_host_unregistered.*restore"):
        execution_machine(
            Mock(), {"id": "single", "machine_lease_id": 42}, _case("linux")
        )


def test_one_corrected_case_cannot_silently_choose_between_original_hosts():
    conn = Mock()
    conn.execute.side_effect = [
        Mock(fetchall=lambda: [{"id": 12}, {"id": 14}]),
        Mock(
            fetchone=lambda: {
                "raw_result": json.dumps({"evidence": {"machine": "linux-lab"}})
            }
        ),
        Mock(
            fetchone=lambda: {
                "raw_result": json.dumps({"evidence": {"machine": "test-mac"}})
            }
        ),
    ]
    with pytest.raises(ValueError, match="qa_resume_correction_hosts_conflict.*split"):
        corrected_case_machine(conn, 15)


def test_wait_recipe_is_rendered_from_its_execution_instead_of_saved_text(monkeypatch):
    from yoke_core.domain import qa_host_turns

    monkeypatch.setattr(
        qa_host_turns,
        "query_one",
        lambda *a, **k: {
            "id": "walk",
            "deployment_run_id": "run",
            "deployment_stage": "item-qa",
            "roster_json": json.dumps([{"project": "example"}]),
        },
    )
    command = qa_host_turns._resume_command(
        Mock(),
        {
            "qa_plan_execution_id": "walk",
            "resume_command": "saved command --machine linux-lab",
        },
    )
    assert command == "yoke qa plan run --resume-execution-id walk"
