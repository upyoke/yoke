"""Both Linux execution adapters redact desktop credentials in receipts."""

import json
import subprocess
from types import SimpleNamespace

from yoke_core.domain import host_control_runner as runner
from yoke_core.domain import machine_qa_local_execution as local
from yoke_core.domain.ssh_linux_host_control import SshLinuxHostControl
from yoke_harness.ssh_linux_host_operations import SshLinuxHostOperations
from yoke_harness.test_machine_operations import execute_host_operation_contract
from yoke_harness.test_machine_types import HostActionResult

PASSWORD = "only-desktop-stdin-secret"
SETTINGS = {
    "resource_name": "lab",
    "host": "lab.invalid",
    "user": "tester",
    "os": "linux",
    "operating_notes": "",
}


def test_core_material_contains_exact_machine_password_without_printing_it(
    tmp_path, monkeypatch
):
    calls = []

    def read(project, capability, key):
        calls.append((project, capability, key))
        return PASSWORD if key == "desktop_password" else "shared-private-key"

    monkeypatch.setattr(runner, "read_machine_capability_secret", read)
    monkeypatch.setattr(
        runner, "machine_capability_secret_path", lambda *a: tmp_path / "key"
    )
    material = runner.materialize_test_machine_contract(
        {"project_id": 1, "project": "project", "settings": SETTINGS}
    )
    assert calls[-1] == ("project", "test-machine:lab", "desktop_password")
    assert material.secrets["desktop_password"] == PASSWORD
    assert PASSWORD not in repr(material)
    monkeypatch.setattr(
        SshLinuxHostOperations,
        "_host_facts",
        lambda self: {"home": "/home/tester", "shell": "/bin/bash"},
    )
    control = SshLinuxHostControl(material)
    assert control.desktop_password == PASSWORD and PASSWORD in control.secret_values


def test_gui_mission_reports_session_and_redacts_password(monkeypatch):
    completed = subprocess.CompletedProcess(
        [], 0, PASSWORD + " output", PASSWORD + " diagnostic"
    )
    completed.desktop_session = "started"
    execution = SimpleNamespace(
        control=SimpleNamespace(run_command=lambda *a, **kw: completed),
        material=SimpleNamespace(secrets={"desktop_password": PASSWORD}),
    )
    monkeypatch.setattr(local, "_mission_contract", lambda value: value)
    monkeypatch.setattr(local, "_execution", lambda *a: execution)
    monkeypatch.setattr(local, "_mission_manages_packages", lambda *a: False)
    result = local.execute_agent_mission_host_command(
        {}, argv=["true"], gui_session=True, timeout_seconds=60
    )
    assert result["desktop_session"] == "started"
    assert PASSWORD not in json.dumps(result)
    assert "[REDACTED]" in result["stdout"] + result["stderr"]


def test_screenshot_submission_cannot_carry_password_into_logs_or_events():
    from yoke_contracts.machine_qa_execution import issue_execution_contract

    contract = issue_execution_contract(
        operation="screenshot",
        lease_id=1,
        lease_key="QA_HOST:lab",
        project_id=1,
        project="project",
        settings=SETTINGS,
    ).model_dump(mode="json")
    control = SimpleNamespace(
        secret_values=(PASSWORD,),
        capture_screenshot=lambda: HostActionResult(
            False,
            {"diagnostic": PASSWORD, "desktop_session": "started"},
            "capture_failed",
        ),
    )
    result = execute_host_operation_contract(
        contract, operations_factory=lambda *a: control
    )
    assert PASSWORD not in json.dumps(result.payload)
    assert result.payload["checks"][0]["diagnostic"] == "[REDACTED]"
    assert result.payload["checks"][0]["desktop_session"] == "started"
