"""Executable missions use the harness-native informed walker."""

from __future__ import annotations

import base64
import json
import shlex
import subprocess
import sys
from pathlib import Path

import pytest

from yoke_core.domain.qa_method_config_validation import (
    QaMethodConfigError,
    validate_method_config,
)
from runtime.api.domain.test_agent_mission_browser_choice import _walker


@pytest.mark.parametrize(
    "executor", ["naive_target_session", "target_machine_agent_session", "", None]
)
def test_unsupported_executor_refuses_authoring_and_pending_dispatch(executor) -> None:
    for operation in (
        lambda: validate_method_config("agent-mission", {"executor": executor}),
        lambda: _walker(executor),
    ):
        with pytest.raises(QaMethodConfigError) as caught:
            operation()
        assert "agent_mission_executor_invalid" in str(caught.value)
        assert "informed_subagent" in str(caught.value)
        assert "rematerialize" in str(caught.value)


def test_informed_dispatch_drives_target_and_uploads_bytes_from_controller() -> None:
    walker = _walker("informed_subagent")
    assert walker["dispatch_kind"] == "subagent"
    assert walker["subagent_type"] == "yoke-qa-walker"
    assert walker["context_policy"] == "project-informed"
    assert (
        "--content-file LOCAL_PATH [--filename NAME]" in walker["artifact_add_command"]
    )
    assert "--content-base64" not in walker["prompt"]
    assert "-- base64 -i TARGET_PATH | python3 -c" in walker["prompt"]
    assert "> LOCAL_PATH" in walker["prompt"]
    assert "pipefail enabled" in walker["prompt"]
    assert "your own local scratch" in walker["prompt"]
    assert "mission scratch path is on the target" in walker["prompt"]
    assert "never a path on the target" in walker["prompt"]
    assert walker["walk_start_command"] in walker["prompt"]
    assert walker["walk_end_command"] in walker["prompt"]


def test_latest_machine_pack_example_is_an_executable_informed_mission() -> None:
    root = Path(__file__).resolve().parents[3]
    pack_root = root / "packs/machine-qa"
    catalog = json.loads((pack_root / "pack.json").read_text())
    version = catalog["versions"][catalog["latest_version"]]
    cases = json.loads(
        (
            pack_root / version["source"] / "qa/examples/installer-exploration.json"
        ).read_text()
    )
    for case in cases:
        assert validate_method_config("agent-mission", case["method_config"]) == {
            "executor": "informed_subagent",
            "os": "macos",
        }
        assert case["host_baselines"] == ["fresh-host"]
        assert "without a source checkout" in case["instructions"]


@pytest.mark.parametrize("wrapped", [False, True])
def test_taught_evidence_decoder_preserves_large_binary_payload(
    tmp_path, wrapped
) -> None:
    walker = _walker("informed_subagent")
    prompt = walker["prompt"]
    pipeline = next(part for part in prompt.split("`") if "| python3 -c" in part)
    assert pipeline.startswith(
        walker["host_command"].removesuffix(" -- ARGV...") + " -- base64 -i TARGET_PATH"
    )
    decoder = pipeline.split(" | ", 1)[1].removesuffix(" > LOCAL_PATH")
    argv = shlex.split(decoder)
    assert argv[0] == "python3"
    payload = bytes(range(256)) * (3 * 4096)
    encoded = (base64.encodebytes if wrapped else base64.b64encode)(payload)
    response = json.dumps({"stdout": encoded.decode("ascii"), "exit_code": 0})
    local_file = tmp_path / "evidence.png"
    with local_file.open("wb") as output:
        subprocess.run(
            [sys.executable, *argv[1:]],
            input=response.encode(),
            stdout=output,
            check=True,
        )
    assert local_file.read_bytes() == payload
