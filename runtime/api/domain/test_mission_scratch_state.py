"""Walk-end counts scratch removed only when removal exits 0 and absence is proved.

A probe that never ran (SSH lost 255, timeout 124, command missing 127) must
refuse with ``mission_scratch_state_unknown``, never read as removed. Both the
POSIX and the native Windows implementations are held to that.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.test_native_windows_mission_operations import (
    FakeWindowsHost,
)
from yoke_contracts.machine_qa_execution import HOST_TEST_COMMAND
from yoke_core.domain import agent_mission_walk_cli, machine_qa_mission_walk
from yoke_core.domain.machine_qa_mission_scratch import (
    MissionScratchStateUnknownError,
    mission_scratch_present,
    remove_mission_scratch,
)
from yoke_harness.native_windows.mission import WINDOWS_SCRATCH_ABSENT_EXIT


EXECUTION_ID = "01JQ8P4Z9K2M7V6T5R3N1B0AXY"
DID_NOT_RUN = (255, 124, 127)


class _PosixHost(FakeHostControl):
    """A POSIX host whose removal and probe exit as scripted."""

    def __init__(self, *, removal: int = 0, probe: int | None = None) -> None:
        super().__init__()
        self.removal, self.probe = removal, probe

    def run_command(self, argv, *, required_session_context=None, timeout=60):
        command = list(argv)
        if command[:2] == ["/bin/rm", "-rf"] and self.removal:
            return subprocess.CompletedProcess(command, self.removal, "", "rm failed")
        if command[:2] == [HOST_TEST_COMMAND, "-e"] and self.probe is not None:
            return subprocess.CompletedProcess(command, self.probe, "", "ssh lost")
        return super().run_command(command, timeout=timeout)


def _windows_host(*, removal: int = 0, probe: int = WINDOWS_SCRATCH_ABSENT_EXIT):
    return FakeWindowsHost(
        {
            "rmdir /s /q": (removal, "", "Access is denied"),
            "exit 3": (probe, "", "ssh lost"),
        }
    )


HOSTS = {
    "posix": lambda **kw: _PosixHost(**kw),
    "windows": lambda **kw: _windows_host(**kw),
}
ABSENT = {"posix": 1, "windows": WINDOWS_SCRATCH_ABSENT_EXIT}


@pytest.mark.parametrize("os_name", sorted(HOSTS))
def test_nonzero_removal_is_not_removed_even_when_the_probe_finds_nothing(os_name):
    host = HOSTS[os_name](removal=1, probe=ABSENT[os_name])
    result = remove_mission_scratch(host, execution_id=EXECUTION_ID)
    assert result["removed"] is False
    assert result["removal_exit_code"] == 1


@pytest.mark.parametrize("exit_code", DID_NOT_RUN)
@pytest.mark.parametrize("os_name", sorted(HOSTS))
def test_a_probe_that_never_ran_refuses_removal(os_name, exit_code):
    host = HOSTS[os_name](probe=exit_code)
    with pytest.raises(MissionScratchStateUnknownError) as refusal:
        remove_mission_scratch(host, execution_id=EXECUTION_ID)
    message = str(refusal.value)
    assert "mission_scratch_state_unknown" in message
    assert f"exited {exit_code}" in message and "Restore SSH access" in message


@pytest.mark.parametrize("exit_code", DID_NOT_RUN)
@pytest.mark.parametrize("os_name", sorted(HOSTS))
def test_a_probe_that_never_ran_refuses_presence(os_name, exit_code):
    host = HOSTS[os_name](probe=exit_code)
    with pytest.raises(MissionScratchStateUnknownError):
        mission_scratch_present(host, execution_id=EXECUTION_ID)


def _walk_end(monkeypatch: Any, host: Any) -> int:
    contract = SimpleNamespace(
        plan_execution_id=EXECUTION_ID,
        cases=[
            SimpleNamespace(
                starting_state="baseline", host_baseline="fresh-host", project="yoke"
            )
        ],
        settings={"resource_name": "lab"},
    )
    execution = SimpleNamespace(
        control=host,
        material=SimpleNamespace(secrets={}),
        reach_baseline=lambda name: SimpleNamespace(
            ok=True, error_code=None, evidence={"name": name}
        ),
    )
    monkeypatch.setattr(
        agent_mission_walk_cli,
        "resolve_mission_contract",
        lambda parsed, *, prog: {"contract": "issued"},
    )
    monkeypatch.setattr(agent_mission_walk_cli, "_register", lambda: None)
    monkeypatch.setattr(machine_qa_mission_walk, "_mission_contract", lambda raw: contract)
    monkeypatch.setattr(machine_qa_mission_walk, "_execution", lambda c: execution)
    monkeypatch.setattr(
        machine_qa_mission_walk, "record_mission_restore", lambda **kwargs: None
    )
    return agent_mission_walk_cli.main(
        ["end", "--item", "ITEM-4550", "--execution-id", EXECUTION_ID]
        + ["--requirement-id", "18152", "--run-id", "991"]
    )


@pytest.mark.parametrize("os_name", sorted(HOSTS))
def test_walk_end_refuses_when_removal_exits_nonzero(monkeypatch, capsys, os_name):
    host = HOSTS[os_name](removal=1, probe=ABSENT[os_name])
    assert _walk_end(monkeypatch, host) == 3
    err = capsys.readouterr().err
    assert "mission_scratch_not_removed" in err and "removal exited 1" in err


@pytest.mark.parametrize("exit_code", DID_NOT_RUN)
@pytest.mark.parametrize("os_name", sorted(HOSTS))
def test_walk_end_refuses_when_the_probe_never_ran(
    monkeypatch, capsys, os_name, exit_code
):
    host = HOSTS[os_name](probe=exit_code)
    assert _walk_end(monkeypatch, host) == 2
    err = capsys.readouterr().err
    assert "mission_scratch_state_unknown" in err and "re-run this command" in err


@pytest.mark.parametrize("os_name", sorted(HOSTS))
def test_walk_end_reports_a_proven_removal(monkeypatch, capsys, os_name):
    host = HOSTS[os_name](probe=ABSENT[os_name])
    assert _walk_end(monkeypatch, host) == 0
    assert '"removed": true' in capsys.readouterr().out
