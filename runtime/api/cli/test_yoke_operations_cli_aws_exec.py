from __future__ import annotations

import types

from yoke_cli.commands.adapters import aws as aws_adapter
from yoke_contracts.api.function_call import FunctionCallResponse, FunctionError


class Completed:
    def __init__(self, returncode: int) -> None:
        self.returncode = returncode


def _settings_response(settings_json: str | None) -> FunctionCallResponse:
    return FunctionCallResponse(
        success=True,
        function="projects.capability_settings.get",
        version="v1",
        result={"settings_json": settings_json} if settings_json is not None else {},
    )


def test_aws_exec_relays_settings_and_uses_machine_capability_env(monkeypatch):
    """https-safe path: settings via dispatcher, secrets via machine store."""
    calls: list[dict[str, object]] = []
    dispatcher_calls: list[dict[str, object]] = []
    fake_deploy_remote = types.SimpleNamespace(
        aws_machine_capability_env=lambda project, region: {
            "AWS_ACCESS_KEY_ID": "AKIATEST",
            "AWS_SECRET_ACCESS_KEY": "secret",
            "AWS_DEFAULT_REGION": region,
            "AWS_REGION": region,
            "AWS_PAGER": "",
        },
        aws_capability_env=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("DB-backed aws_capability_env consulted")
        ),
        aws_capability_region=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("DB-backed aws_capability_region consulted")
        ),
    )
    monkeypatch.setattr(
        aws_adapter.importlib,
        "import_module",
        lambda name: fake_deploy_remote,
    )
    monkeypatch.setattr(aws_adapter, "ensure_handlers_loaded", lambda: None)

    def fake_dispatcher(**kwargs):
        dispatcher_calls.append(kwargs)
        return _settings_response('{"region": "us-east-1"}')

    monkeypatch.setattr(aws_adapter, "call_dispatcher", fake_dispatcher)

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
    assert len(dispatcher_calls) == 1
    assert dispatcher_calls[0]["function_id"] == "projects.capability_settings.get"
    assert dispatcher_calls[0]["payload"] == {
        "project": "yoke",
        "cap_type": "aws-admin",
    }


def test_aws_exec_explicit_region_skips_settings_relay(monkeypatch):
    fake_deploy_remote = types.SimpleNamespace(
        aws_machine_capability_env=lambda project, region: {"AWS_REGION": region},
        aws_capability_env=lambda *_a, **_k: (_ for _ in ()).throw(
            AssertionError("DB-backed aws_capability_env consulted")
        ),
    )
    monkeypatch.setattr(
        aws_adapter.importlib,
        "import_module",
        lambda name: fake_deploy_remote,
    )
    monkeypatch.setattr(
        aws_adapter,
        "call_dispatcher",
        lambda **_k: (_ for _ in ()).throw(AssertionError("settings relayed")),
    )
    monkeypatch.setattr(
        aws_adapter.subprocess,
        "run",
        lambda argv, *, env: Completed(7),
    )

    rc = aws_adapter.aws_exec([
        "--project", "externalwebapp",
        "--region", "us-west-2",
        "--",
        "ec2", "describe-instances",
    ])

    assert rc == 7


def test_aws_exec_missing_region_refuses_before_subprocess(monkeypatch, capsys):
    fake_deploy_remote = types.SimpleNamespace(
        aws_machine_capability_env=lambda project, region: {"AWS_REGION": region},
    )
    monkeypatch.setattr(
        aws_adapter.importlib,
        "import_module",
        lambda name: fake_deploy_remote,
    )
    monkeypatch.setattr(aws_adapter, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        aws_adapter,
        "call_dispatcher",
        lambda **_k: _settings_response("{}"),
    )
    monkeypatch.setattr(
        aws_adapter.subprocess,
        "run",
        lambda argv, *, env: (_ for _ in ()).throw(AssertionError("ran aws")),
    )

    rc = aws_adapter.aws_exec(["--project", "yoke", "--", "sts"])

    assert rc == 1
    assert "settings declare no region" in capsys.readouterr().err


def test_aws_exec_settings_relay_failure_surfaces_error(monkeypatch, capsys):
    monkeypatch.setattr(aws_adapter, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        aws_adapter,
        "call_dispatcher",
        lambda **_k: FunctionCallResponse(
            success=False,
            function="projects.capability_settings.get",
            version="v1",
            error=FunctionError(
                code="TRANSPORT",
                message="control plane unreachable",
            ),
        ),
    )
    monkeypatch.setattr(
        aws_adapter.subprocess,
        "run",
        lambda argv, *, env: (_ for _ in ()).throw(AssertionError("ran aws")),
    )

    rc = aws_adapter.aws_exec(["--project", "platform", "--", "sts"])

    assert rc == 1
    assert "control plane unreachable" in capsys.readouterr().err


def test_aws_exec_missing_binary_returns_127(monkeypatch):
    fake_deploy_remote = types.SimpleNamespace(
        aws_machine_capability_env=lambda project, region: {"AWS_REGION": region},
    )
    monkeypatch.setattr(
        aws_adapter.importlib,
        "import_module",
        lambda name: fake_deploy_remote,
    )
    monkeypatch.setattr(aws_adapter, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        aws_adapter,
        "call_dispatcher",
        lambda **_k: _settings_response('{"region": "us-east-1"}'),
    )

    def fake_run(argv, *, env):
        raise FileNotFoundError

    monkeypatch.setattr(aws_adapter.subprocess, "run", fake_run)

    assert aws_adapter.aws_exec(["--", "sts", "get-caller-identity"]) == 127


def test_aws_exec_requires_aws_args(capsys):
    rc = aws_adapter.aws_exec(["--project", "yoke", "--"])

    assert rc == 2
    assert "missing AWS CLI arguments" in capsys.readouterr().err
