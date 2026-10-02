"""Mission approvals share recipe authority and never read outside their scratch."""

import json
import subprocess
from types import SimpleNamespace

import pytest

from runtime.api.domain.machine_qa_browser_flow_test_support import (
    EXAMPLE_FLOW,
    EXAMPLE_ORIGIN,
)
from yoke_core.domain import machine_qa_mission_browser_flow as mission
from yoke_core.domain.machine_qa_saved_profile_approval import BrowserApprovalResult


class LocalControl:
    def run_command(self, argv, **kwargs):
        return subprocess.run(argv, capture_output=True, text=True, **kwargs)


def test_transcript_scope_is_checked_before_host_access(tmp_path):
    with pytest.raises(ValueError, match="outside_scratch"):
        mission._transcript_reader(
            None, str(tmp_path / "scratch"), str(tmp_path / "other")
        )


@pytest.mark.parametrize("unsafe", ["file_mode", "parent_mode", "symlink", "oversize"])
def test_transcript_file_refuses_unsafe_or_unbounded_input(tmp_path, unsafe):
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    path = scratch / "installer.log"
    if unsafe == "symlink":
        path.symlink_to(tmp_path / "outside")
    else:
        path.write_text("x" * (129 * 1024) if unsafe == "oversize" else "output")
        path.chmod(0o644 if unsafe == "file_mode" else 0o600)
    if unsafe == "parent_mode":
        scratch.chmod(0o755)
    read = mission._transcript_reader(LocalControl(), str(scratch), str(path))
    with pytest.raises(ValueError, match="mission_browser_transcript_"):
        read()


def test_live_transcript_is_read_without_returning_other_files(tmp_path):
    scratch = tmp_path / "scratch"
    scratch.mkdir(mode=0o700)
    path = scratch / "installer.log"
    path.write_text("live output")
    path.chmod(0o600)
    assert (
        mission._transcript_reader(LocalControl(), str(scratch), str(path))()
        == "live output"
    )


def test_mission_uses_the_same_gate_and_requires_terminal_completion(monkeypatch):
    raw = {"server_issued": True}
    contract = SimpleNamespace(project_id=1)
    control = object()
    execution = SimpleNamespace(
        control=control, allowed_operator_urls=(EXAMPLE_ORIGIN,)
    )
    monkeypatch.setattr(
        mission, "_mission_contract", lambda value: contract if value is raw else None
    )
    monkeypatch.setattr(
        mission, "_execution", lambda value: execution if value is contract else None
    )
    monkeypatch.setattr(mission, "load_browser_flow", lambda *_: EXAMPLE_FLOW)
    printed = f"Open: {EXAMPLE_ORIGIN}/connect\nOne-time code: AB12-CD34\n"
    transcripts = iter((printed, printed + "Device connected."))
    monkeypatch.setattr(
        mission, "_transcript_reader", lambda *_: lambda: next(transcripts)
    )
    calls = []

    def approve(selected, **kwargs):
        assert selected is control
        calls.append(kwargs)
        return BrowserApprovalResult(True, {"browser": "candidate-daemon"})

    monkeypatch.setattr(mission, "approve_machine_from_profile", approve)
    result = mission.execute_agent_mission_browser_flow(
        raw,
        execution_id="mission",
        transcript_path="/unused",
        completion_text=["Device connected."],
        timeout_seconds=30,
    )
    assert result["ok"] and result["completion_proved"]
    assert calls[0]["verification_url"] == EXAMPLE_ORIGIN + "/connect"
    assert calls[0]["flow"] is EXAMPLE_FLOW
    assert "transcript" not in result
    assert "AB12-CD34" not in json.dumps(result)
