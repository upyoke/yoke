"""host-copy writes a leased host's file locally, or prints its named refusal."""

from __future__ import annotations

import hashlib
import json

import pytest

from runtime.api.domain.machine_qa_test_support import FakeHostControl
from runtime.api.domain.test_agent_mission_host_access import (  # noqa: F401
    COMPANION,
    DRIVER,
    mission,
)
from yoke_contracts.qa_artifact_limits import MAX_ARTIFACT_BYTES
from yoke_contracts.qa_mission_scratch import MISSION_SCRATCH_ROOT
from yoke_core.domain import agent_mission_host_copy_cli
from yoke_core.domain.agent_mission_host_copy_cli import (
    execute_agent_mission_host_copy,
)
from yoke_core.domain.agent_mission_recording import handle_agent_mission_access
from yoke_core.domain.host_control_runner import (
    clear_host_control_factory,
    register_host_control_factory,
)
from yoke_harness.remote_file_copy import HostCopyRefused

PAYLOAD = b"\x89PNG\r\n\x1a\n" + bytes(range(256)) * 64 + b"\xff\xfe"


@pytest.mark.parametrize("test_machine", [None, COMPANION])
def test_copy_uses_the_selected_lease_and_writes_exact_bytes(
    tmp_path, mission, test_machine  # noqa: F811 - imported fixture
):
    request, _ = mission
    if test_machine is not None:
        request = request.model_copy(
            update={"payload": {**request.payload, "test_machine": test_machine}}
        )
    outcome = handle_agent_mission_access(request)
    assert outcome.primary_success, outcome.error
    calls = []

    class CopyControl(FakeHostControl):
        def copy_file_to(self, path, destination, *, max_bytes, refused_root):
            calls.append((path, max_bytes, refused_root))
            destination.write_bytes(PAYLOAD)
            return len(PAYLOAD)

    materials = []

    def factory(material):
        materials.append(material.settings["resource_name"])
        return CopyControl()

    destination = tmp_path / "shot.png"
    register_host_control_factory(factory)
    try:
        result = execute_agent_mission_host_copy(
            outcome.result_payload["execution"],
            source="/Users/tester/Desktop/shot.png",
            destination=destination,
        )
    finally:
        clear_host_control_factory()
    assert materials == [test_machine or DRIVER]
    assert calls == [
        ("/Users/tester/Desktop/shot.png", MAX_ARTIFACT_BYTES, MISSION_SCRATCH_ROOT)
    ]
    assert destination.read_bytes() == PAYLOAD
    assert result == {
        "from": "/Users/tester/Desktop/shot.png",
        "to": str(destination),
        "bytes": len(PAYLOAD),
        "sha256": hashlib.sha256(PAYLOAD).hexdigest(),
    }


ARGS = [
    "--item",
    "YOK-42",
    "--execution-id",
    "exec-1",
    "--requirement-id",
    "9",
    "--from",
    "/tmp/yoke-qa-mission/exec-1/token",
    "--to",
    "local.bin",
]


def _run(monkeypatch, capsys, execute) -> tuple[int, str, str]:
    monkeypatch.setattr(
        agent_mission_host_copy_cli,
        "resolve_mission_contract",
        lambda parsed, prog: {"operation": "plan_case"},
    )
    monkeypatch.setattr(
        agent_mission_host_copy_cli, "execute_agent_mission_host_copy", execute
    )
    code = agent_mission_host_copy_cli.run(list(ARGS))
    captured = capsys.readouterr()
    return code, captured.out, captured.err


def test_cli_prints_a_refusal_with_its_recovery(monkeypatch, capsys):
    def refuse(contract, *, source, destination):
        raise HostCopyRefused(
            "host_copy_path_in_mission_scratch",
            "token is inside the scratch. Recovery: copy evidence from elsewhere.",
        )

    code, out, err = _run(monkeypatch, capsys, refuse)
    assert code == 2
    assert out == ""
    assert err.startswith(
        "yoke qa mission host-copy: host_copy_path_in_mission_scratch: "
    )
    assert "Recovery: " in err


def test_cli_prints_the_copy_receipt(monkeypatch, capsys):
    def copy(contract, *, source, destination):
        return {"from": source, "to": str(destination), "bytes": 3, "sha256": "x"}

    code, out, err = _run(monkeypatch, capsys, copy)
    assert code == 0
    assert err == ""
    assert json.loads(out) == {
        "bytes": 3,
        "execution_id": "exec-1",
        "from": "/tmp/yoke-qa-mission/exec-1/token",
        "requirement_id": 9,
        "sha256": "x",
        "to": "local.bin",
    }
