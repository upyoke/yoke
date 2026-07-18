"""CLI boundary tests for local Pulumi stack initialization."""

from __future__ import annotations

from contextlib import redirect_stderr
import io

from yoke_cli.commands.adapters import pulumi


def test_pulumi_exec_init_is_local_and_reaches_core_boundary(monkeypatch):
    calls = {}

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
    renderer = type(
        "Renderer", (), {"_resolve_project_root": staticmethod(lambda: ".")},
    )
    monkeypatch.setattr(pulumi, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(pulumi, "resolve_https_connection", lambda: None)
    monkeypatch.setattr(
        pulumi, "build_pulumi_github_auth_loader", lambda **kwargs: object(),
    )
    monkeypatch.setattr(
        pulumi.importlib,
        "import_module",
        lambda name: renderer if name.endswith("project_renderer_values") else executor,
    )

    rc = pulumi.pulumi_exec([
        "--project", "externalwebapp",
        "--stack", "externalwebapp-registry",
        "--", "init", "--secrets-provider",
        "awskms://alias/externalwebapp-pulumi-state?region=us-east-1",
    ])
    assert rc == 0
    assert calls["execute"][0][:3] == (
        "externalwebapp",
        "externalwebapp-registry",
        [
            "init",
            "--secrets-provider",
            "awskms://alias/externalwebapp-pulumi-state?region=us-east-1",
        ],
    )


def test_pulumi_exec_init_refuses_https_before_core_import(monkeypatch):
    monkeypatch.setattr(pulumi, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(pulumi, "resolve_https_connection", lambda: object())
    imported = False

    def import_module(name):
        nonlocal imported
        imported = True
        raise AssertionError(name)

    monkeypatch.setattr(pulumi.importlib, "import_module", import_module)
    stderr = io.StringIO()
    with redirect_stderr(stderr):
        rc = pulumi.pulumi_exec([
            "--project", "externalwebapp",
            "--stack", "externalwebapp-registry",
            "--", "init", "--secrets-provider",
            "awskms://alias/externalwebapp-pulumi-state?region=us-east-1",
        ])
    assert rc == 2
    assert imported is False
    assert "local source-dev/admin boundary" in stderr.getvalue()
