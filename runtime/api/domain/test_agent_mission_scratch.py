"""Lease-scoped secret staging: creation, teardown, and its refusals."""

from __future__ import annotations

import json
import subprocess
from typing import Any

import pytest

from runtime.api.domain.machine_qa_test_support import FakeHostControl
from yoke_contracts.qa_mission_scratch import (
    MISSION_SCRATCH_ROOT,
    MissionScratchIdentityError,
    mission_scratch_path,
)
from yoke_core.domain import agent_mission_scratch_cli
from yoke_core.domain.agent_mission_review import agent_mission_dispatch_contract
from yoke_core.domain.machine_qa_mission_scratch import (
    MissionScratchUnavailableError,
    create_mission_scratch,
    remove_mission_scratch,
)


EXECUTION_ID = "01JQ8P4Z9K2M7V6T5R3N1B0AXY"


class _RefusingHostControl(FakeHostControl):
    """A host that cannot honor one named argv prefix."""

    def __init__(self, *, refuse_prefix: list[str]) -> None:
        super().__init__()
        self._refuse_prefix = list(refuse_prefix)

    def run_command(
        self,
        argv: Any,
        *,
        required_session_context: str | None = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        command = list(argv)
        if command[: len(self._refuse_prefix)] == self._refuse_prefix:
            self.commands.append(command)
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="",
                stderr="Read-only file system",
            )
        return super().run_command(
            command,
            required_session_context=required_session_context,
            timeout=timeout,
        )


def test_scratch_path_is_owned_by_one_plan_execution() -> None:
    path = mission_scratch_path(EXECUTION_ID)
    assert path == f"{MISSION_SCRATCH_ROOT}/{EXECUTION_ID}"


@pytest.mark.parametrize(
    "identity",
    ["", "../escape", "with space", "nested/id", ".hidden", "x" * 129],
)
def test_scratch_path_refuses_an_identity_it_cannot_make_safe(
    identity: str,
) -> None:
    with pytest.raises(MissionScratchIdentityError) as refusal:
        mission_scratch_path(identity)
    assert "execution id" in str(refusal.value)


def test_creation_makes_the_directory_owner_only() -> None:
    control = FakeHostControl()
    path = create_mission_scratch(control, execution_id=EXECUTION_ID)
    assert path == mission_scratch_path(EXECUTION_ID)
    assert control.commands == [
        ["/bin/mkdir", "-p", "-m", "700", path],
        ["/bin/chmod", "700", path],
    ]
    assert path in control.existing_paths


def test_creation_refuses_and_names_the_recovery_when_the_host_cannot() -> None:
    control = _RefusingHostControl(refuse_prefix=["/bin/mkdir"])
    with pytest.raises(MissionScratchUnavailableError) as refusal:
        create_mission_scratch(control, execution_id=EXECUTION_ID)
    message = str(refusal.value)
    assert "mission_scratch_unavailable" in message
    assert mission_scratch_path(EXECUTION_ID) in message
    assert "Read-only file system" in message
    assert "re-run the mission" in message


def test_teardown_removes_the_scratch_and_everything_staged_inside() -> None:
    control = FakeHostControl()
    path = create_mission_scratch(control, execution_id=EXECUTION_ID)
    control.existing_paths.add(f"{path}/first-boot-admin-token")

    result = remove_mission_scratch(control, execution_id=EXECUTION_ID)

    assert result == {
        "scratch_path": path,
        "removed": True,
        "removal_exit_code": 0,
        "removal_stderr": "",
    }
    assert not any(
        existing == path or existing.startswith(f"{path}/")
        for existing in control.existing_paths
    )


def test_teardown_reports_a_scratch_that_survived_removal() -> None:
    control = _RefusingHostControl(refuse_prefix=["/bin/rm"])
    path = create_mission_scratch(control, execution_id=EXECUTION_ID)

    result = remove_mission_scratch(control, execution_id=EXECUTION_ID)

    assert result["scratch_path"] == path
    assert result["removed"] is False
    assert result["removal_exit_code"] == 1
    assert result["removal_stderr"] == "Read-only file system"


class _LeakingHostControl(FakeHostControl):
    """A host whose removal error text echoes a capability secret."""

    def run_command(
        self,
        argv: Any,
        *,
        required_session_context: str | None = None,
        timeout: int = 60,
    ) -> subprocess.CompletedProcess[str]:
        command = list(argv)
        if command[:2] == ["/bin/rm", "-rf"]:
            self.commands.append(command)
            return subprocess.CompletedProcess(
                args=command,
                returncode=1,
                stdout="",
                stderr="rm: cannot remove token top-secret",
            )
        return super().run_command(
            command,
            required_session_context=required_session_context,
            timeout=timeout,
        )


def test_teardown_result_never_carries_a_secret_out_of_the_host(
    monkeypatch: Any,
) -> None:
    from types import SimpleNamespace

    from yoke_core.domain import machine_qa_local_execution

    control = _LeakingHostControl()
    execution = SimpleNamespace(
        control=control,
        material=SimpleNamespace(secrets={"host_token": "top-secret"}),
    )
    monkeypatch.setattr(
        machine_qa_local_execution,
        "_mission_contract",
        lambda raw: SimpleNamespace(plan_execution_id=EXECUTION_ID),
    )
    monkeypatch.setattr(
        machine_qa_local_execution,
        "_execution",
        lambda contract: execution,
    )

    result = machine_qa_local_execution.execute_agent_mission_scratch_teardown(
        {"contract": "issued"}
    )

    assert result["scratch_path"] == mission_scratch_path(EXECUTION_ID)
    assert "top-secret" not in result["removal_stderr"]
    assert "cannot remove token" in result["removal_stderr"]


def test_teardown_command_exits_named_when_the_scratch_survives(
    monkeypatch: Any,
    capsys: Any,
) -> None:
    from yoke_core.domain import machine_qa_local_execution

    surviving = {
        "scratch_path": mission_scratch_path(EXECUTION_ID),
        "removed": False,
        "removal_exit_code": 1,
        "removal_stderr": "Read-only file system",
    }
    monkeypatch.setattr(
        agent_mission_scratch_cli,
        "resolve_mission_contract",
        lambda parsed, *, prog: {"contract": "issued"},
    )
    monkeypatch.setattr(
        machine_qa_local_execution,
        "execute_agent_mission_scratch_teardown",
        lambda contract, *, timeout_seconds: surviving,
    )

    exit_code = agent_mission_scratch_cli.run(
        [
            "--item-id",
            "4550",
            "--execution-id",
            EXECUTION_ID,
            "--requirement-id",
            "18152",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 3
    assert json.loads(captured.out)["removed"] is False
    assert "mission_scratch_not_removed" in captured.err
    assert mission_scratch_path(EXECUTION_ID) in captured.err
    assert "finding against your own walk" in captured.err


def test_walker_dispatch_names_the_scratch_and_its_teardown() -> None:
    execution_target = {
        "project": {"id": 1, "slug": "yoke"},
        "environment": {"name": "stage"},
        "tenant": {"slug": "yoke"},
        "endpoints": {"base_url": "https://stage.example"},
    }
    bundle = {
        "bundle_id": "bundle-1",
        "bundle_digest": "d" * 64,
        "execution_id": EXECUTION_ID,
        "subject": {"item_id": 4550, "deployment_run_id": None},
        "execution_target": execution_target,
        "execution_target_digest": "e" * 64,
        "cases": [
            {
                "requirement_id": 18152,
                "capture_runner": "agent_mission",
                "capture_run_id": 991,
                "executor": "naive_target_session",
                "instructions": "Install as a new user.",
                "expected_outcome": "Ranked findings.",
                "artifacts": [],
                "transcript": {},
            }
        ],
    }

    walker = agent_mission_dispatch_contract(bundle)["walker_dispatches"][0]

    path = mission_scratch_path(EXECUTION_ID)
    assert walker["scratch_path"] == path
    assert walker["scratch_teardown_command"] == (
        "yoke qa mission scratch-teardown --item-id 4550 "
        f"--execution-id {EXECUTION_ID} --requirement-id 18152"
    )
    assert path in walker["prompt"]
    assert walker["scratch_teardown_command"] in walker["prompt"]
    assert "never a loose path under /tmp" in walker["prompt"]
