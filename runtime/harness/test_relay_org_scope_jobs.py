"""Relay execution preserves org workspace identity across supported surfaces."""

import json
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

from yoke_harness import session_relay_runtime as runtime
from yoke_harness import session_relay_working_directory as directories


def job(workspace=None, project_id=None, surface="codex-cli"):
    return {
        "job_kind": "wake",
        "job_id": "attempt",
        "lease_id": "lease",
        "project_id": project_id,
        "surface": surface,
        "target_session_id": "target",
        "target_workspace": str(workspace) if workspace is not None else None,
        "message_id": "message",
        "native_instruction": "Read message message.",
        "wake_mode": "waiting",
        "target_liveness": "ended",
    }


@pytest.mark.parametrize("surface", ["codex-cli", "claude-cli", "cursor-cli"])
def test_org_job_runs_adapter_process_from_session_workspace(
    tmp_path, monkeypatch, surface
):
    observed = []

    def adapter(context):
        result = subprocess.run(
            [sys.executable, "-c", "import os; print(os.getcwd())"],
            cwd=context.checkout,
            check=True,
            capture_output=True,
            text=True,
        )
        observed.append(
            (context.project_id, Path(result.stdout.strip()), context.checkout)
        )
        return runtime.RelayAdapterResult("accepted")

    monkeypatch.setattr(runtime, "_ADAPTERS", {surface: adapter})
    monkeypatch.setattr(
        "yoke_harness.session_relay_native_turn_custody.deferral_for_running_native",
        lambda c: None,
    )
    result = runtime.run_registered_job(
        json.loads(json.dumps(job(tmp_path, surface=surface)))
    )
    assert result.result_code == "accepted"
    assert observed == [(None, tmp_path, tmp_path)]


def test_org_workspace_does_not_read_project_configuration(tmp_path, monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("An org workspace must not resolve any project checkout")

    monkeypatch.setattr(directories, "checkout_for_project", forbidden)
    context = runtime.execution_context(job(tmp_path))
    assert context.project_id is None and context.checkout == tmp_path


@pytest.mark.parametrize("workspace", [None, "", "   "])
def test_org_job_without_workspace_refused_by_name(workspace, monkeypatch):
    monkeypatch.setattr(
        directories,
        "checkout_for_project",
        lambda p: pytest.fail("No project fallback for org job"),
    )
    with pytest.raises(directories.RelayJobSurfaceError) as exc:
        runtime.execution_context(job(workspace))
    assert runtime.RelayJobSurfaceError is directories.RelayJobSurfaceError
    assert exc.value.result_code == "session_workspace_unrecorded"
    assert str(exc.value) == (
        "org-scoped session has no recorded workspace on this machine — terminate it deliberately "
        "(confirm the command with `yoke sessions --help`) or start a new session; project registration does not apply"
    )
    result = runtime.run_registered_job(job(workspace))
    assert result.result_code == "failed"
    assert result.evidence["result_code"] == "session_workspace_unrecorded"


def test_recorded_missing_directory_keeps_its_refusal(tmp_path):
    missing = tmp_path / "missing"
    for project in (None, 1):
        with pytest.raises(directories.RelayJobSurfaceError) as exc:
            runtime.execution_context(job(missing, project_id=project))
        assert exc.value.result_code == "session_workspace_missing"


def test_project_job_checkout_unchanged(tmp_path, monkeypatch):
    configured = [SimpleNamespace(project_id=1, checkout=tmp_path)]
    monkeypatch.setattr(
        directories.machine_config, "configured_projects", lambda **kw: configured
    )
    assert directories.checkout_for_project(1) == tmp_path
    assert directories.checkout_for_project(2) is None
    context = runtime.execution_context(job(project_id=1))
    assert context.project_id == 1 and context.checkout == tmp_path
    with pytest.raises(directories.RelayJobSurfaceError) as exc:
        runtime.execution_context(job(project_id=2))
    assert exc.value.result_code == "checkout_unavailable"


def test_target_workspace_precedes_project_checkout(tmp_path, monkeypatch):
    session = tmp_path / "session"
    session.mkdir()
    monkeypatch.setattr(directories, "checkout_for_project", lambda p: tmp_path)
    assert runtime.execution_context(job(session, project_id=1)).checkout == session


def test_older_workspace_first_wire_shape_runs_org_job(tmp_path):
    wire = json.loads(json.dumps(job(tmp_path)))
    legacy_project = int(wire.get("project_id") or 0)
    legacy_cwd = (
        Path(wire["target_workspace"]) if wire.get("target_workspace") else None
    )
    result = subprocess.run(
        [sys.executable, "-c", "import os; print(os.getcwd())"],
        cwd=legacy_cwd,
        capture_output=True,
        text=True,
        check=True,
    )
    assert legacy_project == 0 and Path(result.stdout.strip()) == tmp_path
    assert runtime.execution_context(wire).project_id is None
