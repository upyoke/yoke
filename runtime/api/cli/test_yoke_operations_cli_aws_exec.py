from __future__ import annotations

import types

from yoke_cli.commands.adapters import aws as aws_adapter


class Completed:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def test_aws_exec_materializes_capability_env_and_forwards_argv(monkeypatch):
    calls: list[dict[str, object]] = []
    fake_deploy_remote = types.SimpleNamespace(
        aws_capability_region=lambda project: "us-east-1",
        aws_capability_env=lambda project, region: {
            "AWS_ACCESS_KEY_ID": "AKIATEST",
            "AWS_SECRET_ACCESS_KEY": "secret",
            "AWS_DEFAULT_REGION": region,
            "AWS_REGION": region,
            "AWS_PAGER": "",
        },
    )
    monkeypatch.setattr(
        aws_adapter.importlib,
        "import_module",
        lambda name: fake_deploy_remote,
    )

    def fake_run(argv, *, env):
        calls.append({"argv": argv, "env": env})
        return Completed(0)

    monkeypatch.setattr(aws_adapter.subprocess, "run", fake_run)

    rc = aws_adapter.aws_exec([
        "--project", "yoke",
        "--",
        "sts", "get-caller-identity",
    ])

    assert rc == 0
    assert calls == [{
        "argv": ["aws", "sts", "get-caller-identity"],
        "env": {
            "AWS_ACCESS_KEY_ID": "AKIATEST",
            "AWS_SECRET_ACCESS_KEY": "secret",
            "AWS_DEFAULT_REGION": "us-east-1",
            "AWS_REGION": "us-east-1",
            "AWS_PAGER": "",
        },
    }]


def test_aws_exec_explicit_region_and_exit_code(monkeypatch):
    fake_deploy_remote = types.SimpleNamespace(
        aws_capability_region=lambda project: None,
        aws_capability_env=lambda project, region: {"AWS_REGION": region},
    )
    monkeypatch.setattr(
        aws_adapter.importlib,
        "import_module",
        lambda name: fake_deploy_remote,
    )
    monkeypatch.setattr(
        aws_adapter.subprocess,
        "run",
        lambda argv, *, env: Completed(7),
    )

    rc = aws_adapter.aws_exec([
        "--project", "buzz",
        "--region", "us-west-2",
        "--",
        "ec2", "describe-instances",
    ])

    assert rc == 7


def test_aws_exec_missing_region_refuses_before_subprocess(monkeypatch, capsys):
    fake_deploy_remote = types.SimpleNamespace(
        aws_capability_region=lambda project: None,
        aws_capability_env=lambda project, region: {"AWS_REGION": region},
    )
    monkeypatch.setattr(
        aws_adapter.importlib,
        "import_module",
        lambda name: fake_deploy_remote,
    )
    monkeypatch.setattr(
        aws_adapter.subprocess,
        "run",
        lambda argv, *, env: (_ for _ in ()).throw(AssertionError("ran aws")),
    )

    rc = aws_adapter.aws_exec(["--project", "yoke", "--", "sts"])

    assert rc == 1
    assert "settings declare no region" in capsys.readouterr().err


def test_aws_exec_missing_binary_returns_127(monkeypatch):
    fake_deploy_remote = types.SimpleNamespace(
        aws_capability_region=lambda project: "us-east-1",
        aws_capability_env=lambda project, region: {"AWS_REGION": region},
    )
    monkeypatch.setattr(
        aws_adapter.importlib,
        "import_module",
        lambda name: fake_deploy_remote,
    )

    def fake_run(argv, *, env):
        raise FileNotFoundError

    monkeypatch.setattr(aws_adapter.subprocess, "run", fake_run)

    assert aws_adapter.aws_exec(["--", "sts", "get-caller-identity"]) == 127


def test_aws_exec_requires_aws_args(capsys):
    rc = aws_adapter.aws_exec(["--project", "yoke", "--"])

    assert rc == 2
    assert "missing AWS CLI arguments" in capsys.readouterr().err
