"""Azure run-command runs fixture scripts as SYSTEM and proves them by record."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from yoke_contracts.machine_fixture_verify import VERIFY_MARKER, MachineFixtureFailed
from yoke_core.domain.azure_instance_power import AzureMachinePower
from yoke_core.domain.deploy_remote import CommandResult
from runtime.api.domain.deploy_remote_test_support import FakeRunner

pytestmark = pytest.mark.windows

ID = "/subscriptions/sub/resourceGroups/lab/providers/Microsoft.Compute/virtualMachines/vm"
RECORD = {"fixture": "grant-admin", "operation": "undo", "ok": True, "state": {"administrator": False}}


def _power(*results):
    runner = FakeRunner(list(results))
    seen = []
    original = runner.run

    def run(argv, **kwargs):
        script = next(a for a in argv if a.startswith("@"))[1:]
        seen.append(Path(script).read_text(encoding="utf-8"))
        return original(argv, **kwargs)

    runner.run = run
    return AzureMachinePower(runner, ("az",), {"AZURE_CONFIG_DIR": "/tmp/az"}, ID, "yoke", lambda line: None), runner, seen


def _output(stdout, stderr=""):
    return CommandResult(0, json.dumps({"value": [
        {"code": "ComponentStatus/StdOut/succeeded", "message": stdout},
        {"code": "ComponentStatus/StdErr/succeeded", "message": stderr},
    ]}), "")


def test_run_script_invokes_run_command_as_system_and_returns_records():
    power, runner, seen = _power(_output("noise\n" + VERIFY_MARKER + json.dumps(RECORD)))
    assert power.run_script("Write-Output 'Zoë'", timeout=900) == [RECORD]
    (call,) = runner.calls
    argv = call["argv"]
    assert argv[:7] == ["az", "vm", "run-command", "invoke", "--ids", ID, "--command-id"]
    assert argv[7] == "RunPowerShellScript" and argv[8] == "--scripts" and argv[-2:] == ["--output", "json"]
    assert call["env"] == {"AZURE_CONFIG_DIR": "/tmp/az"} and call["timeout"] == 900
    assert seen == ["Write-Output 'Zoë'"]


def test_non_zero_cli_exit_refuses_with_stderr():
    power, _, _ = _power(CommandResult(1, "", "Run command extension execution is in progress"))
    with pytest.raises(MachineFixtureFailed) as error:
        power.run_script("x", timeout=60)
    assert error.value.code == "machine_fixture_failed"
    assert "in progress" in error.value.stderr


def test_missing_verify_record_refuses_with_the_script_stderr():
    power, _, _ = _power(_output("no record", "applocker_not_applied: inspect"))
    with pytest.raises(MachineFixtureFailed) as error:
        power.run_script("x", timeout=60)
    assert error.value.records == []
    assert "applocker_not_applied" in error.value.stderr


def test_failed_record_refuses_and_keeps_every_record():
    failed = {**RECORD, "ok": False, "error": "grant_admin_not_undone"}
    power, _, _ = _power(_output(VERIFY_MARKER + json.dumps(RECORD) + "\n" + VERIFY_MARKER + json.dumps(failed)))
    with pytest.raises(MachineFixtureFailed) as error:
        power.run_script("x", timeout=60)
    assert error.value.records == [RECORD, failed]
