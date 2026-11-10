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


def _capture_executor(monkeypatch, *, https: bool, file_backed: bool) -> dict:
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
            "file_backed_stack_path": staticmethod(
                lambda root, stack: Path("infra/Pulumi.x.yaml") if file_backed else None
            ),
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


@pytest.mark.parametrize(
    ("https", "file_backed"), [(False, False), (False, True), (True, True)]
)
def test_pulumi_exec_init_reaches_core_boundary(monkeypatch, https, file_backed):
    calls = _capture_executor(monkeypatch, https=https, file_backed=file_backed)
    assert pulumi.pulumi_exec(list(_INIT)) == 0
    assert calls["execute"][0][:3] == (
        "externalwebapp",
        "externalwebapp-registry",
        ["init", "--secrets-provider", _PROVIDER],
    )


def test_rendered_stack_init_refuses_https_before_core(monkeypatch):
    calls = _capture_executor(monkeypatch, https=True, file_backed=False)
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        rc = pulumi.pulumi_exec(list(_INIT))
    assert rc == 2
    assert "execute" not in calls
    assert "local source-dev/admin boundary" in stderr.getvalue()
    assert "infra/Pulumi.<stack>.yaml" in stderr.getvalue()


def test_init_refuses_bootstrap_local_authority(monkeypatch):
    calls = _capture_executor(monkeypatch, https=False, file_backed=True)
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        rc = pulumi.pulumi_exec(["--bootstrap-local-authority", *_INIT])
    assert rc == 2
    assert "execute" not in calls
