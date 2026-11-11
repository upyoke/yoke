"""CLI boundary tests for Pulumi stack initialization."""

from __future__ import annotations

from contextlib import redirect_stderr
import io
from pathlib import Path

import pytest

from yoke_cli.commands.adapters import pulumi


_PROVIDER = "awskms://alias/externalwebapp-pulumi-state?region=us-east-1"
_INIT = [
    "--project", "externalwebapp",
    "--stack", "externalwebapp-registry",
    "--", "init", "--secrets-provider", _PROVIDER,
]


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


def test_pulumi_exec_init_reaches_core_boundary(monkeypatch):
    calls = _capture_executor(monkeypatch)
    assert pulumi.pulumi_exec(list(_INIT)) == 0
    args, kwargs = calls["execute"]
    assert args[:3] == (
        "externalwebapp",
        "externalwebapp-registry",
        ["init", "--secrets-provider", _PROVIDER],
    )
    assert "config_loader" not in kwargs
    assert kwargs["confirm_destroy"] is None


def test_init_refuses_bootstrap_local_authority(monkeypatch):
    calls = _capture_executor(monkeypatch)
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        rc = pulumi.pulumi_exec(["--bootstrap-local-authority", *_INIT])
    assert rc == 2
    assert "execute" not in calls
