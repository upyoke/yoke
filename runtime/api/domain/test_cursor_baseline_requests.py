"""Cursor's scratch request must not depend on persisted workspace trust."""

from __future__ import annotations

import pytest

from yoke_harness.baseline_harness_requests import REQUEST_WORKSPACE, harness_request
from yoke_harness.ssh_linux_baseline import prove_linux_probes
from yoke_harness.ssh_mac_baseline_probes import prove_probes_document
from runtime.api.domain.test_baseline_harness_requests import _Control


@pytest.mark.parametrize("program", ["cursor-agent", "agent"])
def test_cursor_request_trusts_only_its_scratch_workspace(program):
    request = harness_request([f"/bin/{program}", "--workspace", "/project", "status"])
    assert request.name == "Cursor"
    assert request.argv.count("--trust") == 1
    assert request.argv[request.argv.index("--workspace") + 1] == REQUEST_WORKSPACE
    assert "/project" not in request.argv
    assert request.argv[request.argv.index("--mode") + 1] == "ask"


@pytest.mark.parametrize("program", ["cursor-agent", "agent"])
@pytest.mark.parametrize("platform", ["linux", "macos"])
@pytest.mark.parametrize("stream", ["stdout", "stderr"])
def test_cursor_workspace_trust_refusal_is_never_a_sign_in_failure(
    program, platform, stream
):
    control = _Control(program, returncode=1, stdout="")
    setattr(
        control.result, stream, "Workspace Trust Required\nprivate-account@example.com"
    )
    result = (
        prove_linux_probes(control, control.document)
        if platform == "linux"
        else prove_probes_document(control, control.document)
    )
    assert not result.ok
    assert result.error_code == "baseline_probe_failed"
    row = result.evidence["probes"][0]
    assert row["cause"] == "cursor_workspace_trust_required"
    assert "Workspace Trust Required" in row["reason"]
    assert "--trust --workspace /tmp" in row["recovery"]
    assert "sign-in" not in repr(result.evidence)
    assert "private-account" not in repr(result.evidence)


def test_only_cursor_names_the_workspace_trust_refusal():
    request = harness_request(["/bin/claude"])
    assert request.native_refusal("Workspace Trust Required", "") is None


@pytest.mark.parametrize("program", ["cursor-agent", "agent"])
def test_signed_out_cursor_still_names_its_sign_in_recovery(program):
    control = _Control(program, returncode=1, stdout="")
    control.result.stderr = "Authentication required. Please run agent login."
    result = prove_linux_probes(control, control.document)
    row = result.evidence["probes"][0]
    assert not result.ok
    assert row["cause"] == "probe_harness_exit_nonzero"
    assert "Re-sign-in to Cursor" in row["reason"]
    assert f"/home/test/.local/bin/{program} login" in row["recovery"]
