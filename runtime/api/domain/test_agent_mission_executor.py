"""Executable missions use the harness-native informed walker."""

from __future__ import annotations

import json
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
    assert "--content-base64 B64 --filename NAME" in walker["artifact_add_command"]
    assert "--content-file" not in walker["artifact_add_command"]
    assert "base64 -i TARGET_PATH" in walker["prompt"]
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
            "executor": "informed_subagent", "os": "macos"
        }
        assert case["host_baselines"] == ["fresh-host"]
        assert "without a source checkout" in case["instructions"]
