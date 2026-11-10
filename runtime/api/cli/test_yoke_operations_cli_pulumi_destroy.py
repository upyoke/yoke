"""CLI boundary tests for confirmed Pulumi destroy and stack removal."""

from __future__ import annotations

from contextlib import redirect_stderr
import io
from pathlib import Path

import pytest

from yoke_cli.commands.adapters import pulumi


def _capture_executor(monkeypatch, *, https: bool) -> dict:
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
    monkeypatch.setattr(
        pulumi, "resolve_https_connection", lambda: object() if https else None
    )
    monkeypatch.setattr(pulumi, "_project_checkout", lambda *a, **k: Path("."))
    monkeypatch.setattr(
        pulumi, "build_pulumi_github_auth_loader", lambda **kwargs: object()
    )
    monkeypatch.setattr(pulumi.importlib, "import_module", lambda name: executor)
    return calls


@pytest.mark.parametrize("https", [False, True])
def test_destroy_passes_confirmation_to_core_in_every_mode(monkeypatch, https):
    calls = _capture_executor(monkeypatch, https=https)
    rc = pulumi.pulumi_exec([
        "--project", "app", "--stack", "app-drill-vps",
        "--confirm-destroy", "app-drill-vps",
        "--", "destroy", "--yes", "--non-interactive",
    ])
    assert rc == 0
    args, kwargs = calls["execute"]
    assert args[2] == ["destroy", "--yes", "--non-interactive"]
    assert kwargs["confirm_destroy"] == "app-drill-vps"


def test_stack_rm_is_local_and_reaches_core(monkeypatch):
    calls = _capture_executor(monkeypatch, https=False)
    rc = pulumi.pulumi_exec([
        "--project", "app", "--stack", "app-drill-vps",
        "--confirm-destroy", "app-drill-vps", "--", "stack", "rm", "--yes",
    ])
    assert rc == 0
    assert calls["execute"][1]["confirm_destroy"] == "app-drill-vps"


@pytest.mark.parametrize(
    "command",
    [
        ["stack", "rm", "--yes"],
        ["stack", "--stack", "app-drill-vps", "rm", "--yes"],
        ["stack", "--stack=app-drill-vps", "rm", "--yes"],
    ],
)
def test_stack_rm_refuses_https_before_core(monkeypatch, command):
    calls = _capture_executor(monkeypatch, https=True)
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        rc = pulumi.pulumi_exec([
            "--project", "app", "--stack", "app-drill-vps",
            "--confirm-destroy", "app-drill-vps", "--", *command,
        ])
    assert rc == 2
    assert "execute" not in calls
    assert "pulumi stack rm is a local source-dev/admin boundary" in stderr.getvalue()
