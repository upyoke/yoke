"""VPS power controls use boto3 with machine-local capability authority."""

from __future__ import annotations

import types
from typing import Any

import pytest

from yoke_cli.commands.adapters import vps

_STACK = "acme-stage-vps"
_INSTANCE = "i-0123456789abcdef0"


class _Ec2Client:
    def __init__(self, state: str = "running", failure: BaseException | None = None):
        self.state = state
        self.failure = failure
        self.filters: list[dict[str, Any]] | None = None
        self.power_calls: list[tuple[str, list[str]]] = []

    def describe_instances(self, *, Filters):
        if self.failure is not None:
            raise self.failure
        self.filters = Filters
        return {
            "Reservations": [
                {
                    "Instances": [
                        {
                            "InstanceId": _INSTANCE,
                            "State": {"Name": self.state},
                        }
                    ],
                }
            ],
        }

    def start_instances(self, *, InstanceIds):
        self.power_calls.append(("start", InstanceIds))

    def stop_instances(self, *, InstanceIds):
        self.power_calls.append(("stop", InstanceIds))


def _install_sdk(monkeypatch, client: _Ec2Client, *, client_failure=None):
    calls: list[tuple[str, str, str]] = []

    def machine_aws_client(service: str, project: str, region: str):
        calls.append((service, project, region))
        if client_failure is not None:
            raise client_failure
        return client

    sdk = types.SimpleNamespace(
        machine_aws_client=machine_aws_client,
        safe_aws_error_reason=lambda exc: getattr(exc, "safe_code", type(exc).__name__),
    )
    monkeypatch.setattr(vps.importlib, "import_module", lambda _name: sdk)
    return calls


def _args() -> list[str]:
    return [
        "--stack",
        _STACK,
        "--project",
        "acme-app",
        "--region",
        "eu-west-1",
    ]


def test_status_uses_ec2_sdk_without_an_aws_executable(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("PATH", "")
    client = _Ec2Client()
    calls = _install_sdk(monkeypatch, client)

    assert vps.vps_status(_args()) == 0

    assert calls == [("ec2", "acme-app", "eu-west-1")]
    assert client.filters == [
        {
            "Name": "tag:Name",
            "Values": [f"{_STACK}/VpsInstance"],
        }
    ]
    assert f"{_INSTANCE} is running" in capsys.readouterr().out


@pytest.mark.parametrize(
    ("verb", "state", "expected"),
    [("start", "stopped", "starting"), ("stop", "running", "stopping")],
)
def test_power_verb_calls_the_matching_ec2_api(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    verb: str,
    state: str,
    expected: str,
) -> None:
    client = _Ec2Client(state)
    _install_sdk(monkeypatch, client)

    assert getattr(vps, f"vps_{verb}")(_args()) == 0

    assert client.power_calls == [(verb, [_INSTANCE])]
    assert expected in capsys.readouterr().out


def test_sdk_failure_is_redacted_and_teaches_the_recovery(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    secret = "never-print-this-secret"

    class AccessDenied(RuntimeError):
        safe_code = "AccessDenied"

    client = _Ec2Client(failure=AccessDenied(secret))
    _install_sdk(monkeypatch, client)

    assert vps.vps_stop(_args()) == 1

    error = capsys.readouterr().err
    assert "vps stop failed (AccessDenied)" in error
    assert "yoke aws admin-status --project acme-app" in error
    assert secret not in error


def test_capability_failure_is_named_before_any_ec2_request(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    class CredentialMissing(RuntimeError):
        safe_code = "CredentialMissing"

    _install_sdk(
        monkeypatch,
        _Ec2Client(),
        client_failure=CredentialMissing("secret path"),
    )

    assert vps.vps_status(_args()) == 1

    error = capsys.readouterr().err
    assert "AWS authority (CredentialMissing)" in error
    assert "yoke aws admin-status --project acme-app" in error
    assert "secret path" not in error
