"""Claude relay contracts across a rolling control-plane deployment."""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.config.machine_config import ConfiguredProject
from yoke_contracts.session_control.evidence import redacted_evidence_document
from yoke_contracts.session_control.launch_bootstrap import native_launch_bootstrap
from yoke_harness import session_relay_runtime as runtime
from yoke_harness.session_relay_claude import run_claude_cli_adapter
from yoke_harness.session_relay_native_spawn import SupervisedNative


LAUNCH_ID = "12345678-1234-4234-8234-123456789abc"
CLAUDE = "/opt/claude/bin/claude"


def _started(invocation) -> SupervisedNative:
    return SupervisedNative(
        4242,
        invocation.executable,
        "path",
        Path("/state/native-diagnostics/never-written.capture"),
        "nd-55555555-5555-4555-8555-555555555555",
        "2026-09-03T21:00:00Z",
    )


def _control_plane_job(**updates: object) -> dict[str, object]:
    job: dict[str, object] = {
        "job_kind": "launch",
        "job_id": LAUNCH_ID,
        "lease_id": "lease-1",
        "surface": "claude-cli",
        "surface_version": "2.1.238",
        "project_id": 10,
        "native_instruction": native_launch_bootstrap(LAUNCH_ID),
        "requested_model": "claude-opus-4-1",
        "launch_attestation": "secret-attestation",
    }
    job.update(updates)
    return job


@pytest.fixture
def relay_context(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setattr(
        runtime.machine_config,
        "configured_projects",
        lambda **_kwargs: [ConfiguredProject(tmp_path, 10, {})],
    )

    def build(**updates: object) -> runtime.RelayExecutionContext:
        return runtime.execution_context(_control_plane_job(**updates))

    return build


def test_job_without_new_optional_field_remains_launchable(relay_context) -> None:
    context = relay_context(presentation="local")
    invocations = []

    result = run_claude_cli_adapter(
        context,
        create_spawner=lambda invocation: (
            invocations.append(invocation) or _started(invocation)
        ),
        executable_finder=lambda _name: CLAUDE,
        version_gate=lambda *_args: True,
    )

    assert result.result_code == "native_created"
    assert "--name" not in invocations[0].argv
    assert redacted_evidence_document(result.evidence)["probe_detail"] == (
        "session_name absent: control plane is behind relay; "
        "deploy control plane to converge launch contract"
    )


def test_required_field_gap_names_skew_and_recovery(relay_context) -> None:
    result = run_claude_cli_adapter(relay_context(session_name="named session"))

    assert result.result_code == "not_created"
    assert redacted_evidence_document(result.evidence) == {
        "probe_detail": (
            "presentation absent: control plane is behind relay; "
            "deploy control plane to converge launch contract"
        ),
        "result_code": "control_plane_schema_skew",
        "surface": "claude-cli",
    }
