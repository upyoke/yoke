"""A wake resumes its target session in that session's own workspace.

One session legitimately works across projects, so the project on the message
that wakes it is the addressed item's, not the directory the session runs in.
Resolving the native's working directory from that project sent every surface
looking for a conversation in a checkout it had never run in. The resolution
is central — the surface plays no part in it — so these tests exercise the
one resolver every adapter receives its ``checkout`` from.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from yoke_cli.config.machine_config import ConfiguredProject
from yoke_harness import session_relay_runtime as runtime


PROJECT_ID = 10
SURFACES = ("claude-cli", "codex-cli", "cursor-cli")


@pytest.fixture
def registered_checkout(monkeypatch, tmp_path: Path) -> Path:
    checkout = tmp_path / "beta-checkout"
    checkout.mkdir()
    monkeypatch.setattr(
        runtime.machine_config,
        "configured_projects",
        lambda **_kwargs: [ConfiguredProject(checkout, PROJECT_ID, {})],
    )
    return checkout


def _wake_job(**overrides) -> dict:
    job = {
        "job_kind": "wake",
        "job_id": "attempt-1",
        "lease_id": "lease-1",
        "surface": "claude-cli",
        "surface_version": "2.1.238",
        "project_id": PROJECT_ID,
        "native_instruction": "check inbox for message m1",
        "message_id": "m1",
        "target_session_id": "s4",
    }
    job.update(overrides)
    return job


@pytest.mark.parametrize("surface", SURFACES)
def test_wake_runs_in_the_session_workspace_not_the_message_project(
    registered_checkout: Path,
    tmp_path: Path,
    surface: str,
) -> None:
    workspace = tmp_path / "alpha-checkout"
    workspace.mkdir()

    context = runtime.execution_context(
        _wake_job(surface=surface, target_workspace=str(workspace))
    )

    assert context.checkout == workspace
    # The message's project routing is untouched: it still says which project
    # the envelope was addressed under, and only the directory changed.
    assert context.project_id == PROJECT_ID
    assert context.checkout != registered_checkout


def test_launch_still_starts_in_the_project_checkout(
    registered_checkout: Path,
) -> None:
    """A launch has no session yet, so the project checkout is its home."""
    context = runtime.execution_context(
        {
            "job_kind": "launch",
            "job_id": "launch-1",
            "lease_id": "lease-1",
            "surface": "claude-cli",
            "project_id": PROJECT_ID,
            "native_instruction": "bootstrap launch-1",
        }
    )

    assert context.checkout == registered_checkout


def test_wake_falls_back_to_the_project_checkout_without_a_workspace(
    registered_checkout: Path,
) -> None:
    """A control plane that sends no workspace still gets its wake attempted."""
    assert runtime.execution_context(_wake_job()).checkout == registered_checkout


def test_wake_refuses_by_name_when_the_session_workspace_is_gone(
    registered_checkout: Path,
    tmp_path: Path,
) -> None:
    """A removed lane is named, never silently retried in another checkout."""
    missing = tmp_path / "removed-lane"

    result = runtime.run_registered_job(_wake_job(target_workspace=str(missing)))

    assert result.result_code == "failed"
    assert result.evidence["result_code"] == "session_workspace_missing"
    assert result.evidence["session_workspace"] == str(missing)
