"""Mission walks: scratch staging, walk-start, walk-end, and their refusals."""

from __future__ import annotations

import json
import subprocess
from types import SimpleNamespace
from typing import Any

import pytest

from runtime.api.domain.machine_qa_test_support import FakeHostControl
from yoke_contracts.qa_mission_scratch import (
    MISSION_SCRATCH_ROOT,
    MissionScratchIdentityError,
    mission_scratch_path,
    stale_owner_marker_remove_argv,
)
from yoke_core.domain import agent_mission_walk_cli, machine_qa_mission_walk
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
    scratch = create_mission_scratch(control, execution_id=EXECUTION_ID)
    path = scratch["scratch_path"]
    assert path == mission_scratch_path(EXECUTION_ID)
    assert scratch == {"scratch_path": path}
    assert control.commands == [
        ["/bin/mkdir", "-p", "-m", "700", path],
        ["/bin/chmod", "700", path],
        stale_owner_marker_remove_argv(),
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
    path = create_mission_scratch(control, execution_id=EXECUTION_ID)["scratch_path"]
    control.existing_paths.add(f"{path}/first-boot-admin-token")

    result = remove_mission_scratch(control, execution_id=EXECUTION_ID)

    assert result == {
        "scratch_path": path,
        "removed": True,
        "removal_exit_code": 0,
        "removal_stderr": "",
        "stale_owner_marker_removed": True,
    }
    assert not any(
        existing == path or existing.startswith(f"{path}/")
        for existing in control.existing_paths
    )


def test_teardown_reports_a_scratch_that_survived_removal() -> None:
    control = _RefusingHostControl(refuse_prefix=["/bin/rm"])
    path = create_mission_scratch(control, execution_id=EXECUTION_ID)["scratch_path"]

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


def _walk_contract(starting_state: str = "baseline") -> Any:
    case = SimpleNamespace(
        starting_state=starting_state,
        host_baseline="fresh-host" if starting_state == "baseline" else None,
        project="yoke",
    )
    return SimpleNamespace(
        plan_execution_id=EXECUTION_ID,
        cases=[case],
        settings={"resource_name": "mac-mini-lab"},
    )


def _patch_execution(monkeypatch: Any, control: Any, contract: Any) -> list[str]:
    reached: list[str] = []

    def reach(name: str) -> Any:
        reached.append(name)
        return SimpleNamespace(ok=True, error_code=None, evidence={"name": name})

    execution = SimpleNamespace(
        control=control,
        material=SimpleNamespace(secrets={"host_token": "top-secret"}),
        reach_baseline=reach,
    )
    monkeypatch.setattr(
        machine_qa_mission_walk, "_mission_contract", lambda raw: contract
    )
    monkeypatch.setattr(machine_qa_mission_walk, "_execution", lambda c: execution)
    return reached


def test_walk_end_removes_scratch_then_restores_the_declared_baseline(
    monkeypatch: Any,
) -> None:
    control = _LeakingHostControl()
    reached = _patch_execution(monkeypatch, control, _walk_contract())

    result = machine_qa_mission_walk.execute_agent_mission_walk_end({"c": 1})

    assert result["scratch_path"] == mission_scratch_path(EXECUTION_ID)
    assert "top-secret" not in result["removal_stderr"]
    assert "cannot remove token" in result["removal_stderr"]
    assert reached == ["fresh-host"]
    assert result["starting_state_restore"]["restored"] is True
    assert result["starting_state_restore"]["baseline"] == "fresh-host"


def test_walk_end_of_an_as_is_mission_says_there_is_nothing_to_restore(
    monkeypatch: Any,
) -> None:
    reached = _patch_execution(monkeypatch, FakeHostControl(), _walk_contract("as_is"))

    result = machine_qa_mission_walk.execute_agent_mission_walk_end({"c": 1})

    assert reached == []
    assert result["starting_state_restore"]["restored"] is False
    assert "no declared starting state" in result["starting_state_restore"]["reason"]


def _run_walk_end(monkeypatch: Any, result: dict, unrecorded: str | None) -> int:
    recorded: list[dict] = []
    monkeypatch.setattr(
        agent_mission_walk_cli,
        "resolve_mission_contract",
        lambda parsed, *, prog: {"contract": "issued"},
    )
    monkeypatch.setattr(
        machine_qa_mission_walk,
        "execute_agent_mission_walk_end",
        lambda contract, *, timeout_seconds: result,
    )

    def record(**kwargs: Any) -> str | None:
        recorded.append(kwargs)
        return unrecorded

    monkeypatch.setattr(machine_qa_mission_walk, "record_mission_restore", record)
    exit_code = agent_mission_walk_cli.main(
        ["end", "--item", f"ITEM-{4550}", "--execution-id", EXECUTION_ID]
        + ["--requirement-id", "18152", "--run-id", "991"]
    )
    assert recorded and recorded[0]["run_id"] == 991
    return exit_code


def _walk_result(**overrides: Any) -> dict:
    return {
        "scratch_path": mission_scratch_path(EXECUTION_ID),
        "removed": True,
        "removal_exit_code": 0,
        "removal_stderr": "",
        "stale_owner_marker_removed": True,
        "starting_state_restore": {"restored": True, "baseline": "fresh-host"},
        **overrides,
    }


def test_walk_end_records_the_restore_and_exits_clean(monkeypatch, capsys):
    assert _run_walk_end(monkeypatch, _walk_result(), None) == 0
    assert json.loads(capsys.readouterr().out)["starting_state_restore"]["restored"]


def test_walk_end_names_each_thing_it_could_not_finish(monkeypatch, capsys):
    failed = {
        "restored": False,
        "baseline": "fresh-host",
        "error_code": "starting_state_restore_failed",
        "recovery": "run `yoke test-machine reset --project yoke`",
    }
    result = _walk_result(removed=False, starting_state_restore=failed)

    assert _run_walk_end(monkeypatch, result, "not_found: run 991") == 3
    err = capsys.readouterr().err
    assert "mission_scratch_not_removed" in err and "your own walk" in err
    assert "starting_state_restore_failed" in err
    assert "yoke test-machine reset" in err
    assert "starting_state_restore_unrecorded: not_found: run 991" in err


def test_walk_start_refuses_to_walk_when_preparation_failed(monkeypatch, capsys):
    monkeypatch.setattr(
        agent_mission_walk_cli,
        "resolve_mission_contract",
        lambda parsed, *, prog: {"contract": "issued"},
    )
    failure = {"diagnostic": "baseline did not prove", "recovery": "reset it"}
    monkeypatch.setattr(
        machine_qa_mission_walk,
        "execute_agent_mission_walk_start",
        lambda contract: {
            "preparation": {
                "ok": False,
                "error_code": "baseline_operation_failed",
                "evidence": {"preparation_failure": failure},
            }
        },
    )
    exit_code = agent_mission_walk_cli.main(
        ["start", "--item", f"ITEM-{4550}", "--execution-id", EXECUTION_ID]
        + ["--requirement-id", "18152"]
    )
    assert exit_code == 3
    err = capsys.readouterr().err
    assert "baseline_operation_failed" in err and "Do not walk" in err


def test_walker_dispatch_names_the_walk_commands_and_sequential_walks() -> None:
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
        "subject": {"public_ref": "ITEM-4550", "deployment_run_id": None},
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

    contract = agent_mission_dispatch_contract(bundle)
    walker = contract["walker_dispatches"][0]

    flags = f"--item ITEM-{4550} --execution-id {EXECUTION_ID} --requirement-id 18152"
    assert walker["walk_start_command"] == f"yoke qa mission walk-start {flags}"
    assert walker["walk_end_command"] == (
        f"yoke qa mission walk-end {flags} --run-id 991"
    )
    for expected in ("walk_start_command", "walk_end_command"):
        assert walker[expected] in walker["prompt"]
    assert mission_scratch_path(EXECUTION_ID) in walker["prompt"]
    assert "never a loose path under /tmp" in walker["prompt"]
    assert "yoke projects retire --project SLUG" in walker["prompt"]
    assert "one walker at a time" in contract["prompt"]
