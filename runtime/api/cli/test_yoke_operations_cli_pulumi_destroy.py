"""CLI boundary tests for confirmed Pulumi destroy and stack removal."""

from __future__ import annotations

from contextlib import redirect_stderr
import io
from pathlib import Path

import pytest

from yoke_cli.commands.adapters import pulumi


def _capture_executor(monkeypatch) -> dict:
    calls: dict = {}

    def execute(*args, **kwargs):
        calls["execute"] = (args, kwargs)
        return 0

    executor = type(
        "Executor",
        (),
        {
            "aws_machine_capability_env": object(),
            "execute_pulumi_command": staticmethod(execute),
        },
    )
    monkeypatch.setattr(pulumi, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(pulumi, "_project_checkout", lambda *a, **k: Path("."))
    monkeypatch.setattr(
        pulumi, "build_pulumi_github_auth_loader", lambda **kwargs: object()
    )
    monkeypatch.setattr(pulumi.importlib, "import_module", lambda name: executor)
    return calls


def test_destroy_passes_confirmation_to_core(monkeypatch):
    calls = _capture_executor(monkeypatch)
    rc = pulumi.pulumi_exec([
        "--project", "app", "--stack", "app-drill-vps",
        "--confirm-destroy", "app-drill-vps",
        "--", "destroy", "--yes", "--non-interactive",
    ])
    assert rc == 0
    args, kwargs = calls["execute"]
    assert args[2] == ["destroy", "--yes", "--non-interactive"]
    assert kwargs["confirm_destroy"] == "app-drill-vps"


@pytest.mark.parametrize(
    "command",
    [
        ["stack", "rm", "--yes"],
        ["stack", "--stack", "app-drill-vps", "rm", "--yes"],
        ["stack", "--stack=app-drill-vps", "rm", "--yes"],
    ],
)
def test_stack_rm_reaches_core_with_confirmation(monkeypatch, command):
    calls = _capture_executor(monkeypatch)
    rc = pulumi.pulumi_exec([
        "--project", "app", "--stack", "app-drill-vps",
        "--confirm-destroy", "app-drill-vps", "--", *command,
    ])
    assert rc == 0
    args, kwargs = calls["execute"]
    assert args[2] == command
    assert kwargs["confirm_destroy"] == "app-drill-vps"


def test_core_refusal_is_reported_as_failure(monkeypatch):
    _capture_executor(monkeypatch)
    executor = pulumi.importlib.import_module("yoke_core.tools.pulumi_exec")

    def refuse(*args, **kwargs):
        raise RuntimeError("pulumi_stack_file_missing: add infra/Pulumi.x.yaml")

    executor.execute_pulumi_command = staticmethod(refuse)
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        rc = pulumi.pulumi_exec([
            "--project", "app", "--stack", "app-drill-vps", "--", "preview",
        ])
    assert rc == 1
    assert "pulumi_stack_file_missing" in stderr.getvalue()
