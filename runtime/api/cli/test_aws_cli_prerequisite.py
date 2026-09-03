"""The AWS CLI prerequisite check and the surfaces that refuse through it.

A stored access key pair says nothing about whether this machine can run the
executable every capability-owned AWS operation shells out to, so these
scenarios pin the three answers the check gives — not installed, installed off
``PATH``, present but unusable — and prove that the exec wrappers turn each one
into a named reason with recovery rather than a bare failure.
"""

from __future__ import annotations

import subprocess
import types
from pathlib import Path

import pytest

from yoke_cli.commands.adapters import aws as aws_adapter
from yoke_cli.commands.adapters import vps as vps_adapter
from yoke_cli.config import aws_cli_prerequisite as prerequisite


class _Result:
    def __init__(self, returncode: int, stdout: str = "") -> None:
        self.returncode = returncode
        self.stdout = stdout


def _no_known_location(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(prerequisite, "_first_known_location", lambda: None)


def test_reports_the_resolved_executable_and_version(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prerequisite, "_WHICH", lambda _name: "/usr/local/bin/aws")
    monkeypatch.setattr(
        prerequisite, "_RUN", lambda *_a, **_k: _Result(0, "aws-cli/2.34.55 \n"),
    )

    cli = prerequisite.check_aws_cli()

    assert cli.executable == "/usr/local/bin/aws"
    assert cli.version == "aws-cli/2.34.55"


def test_absent_cli_names_the_install_command_for_this_machine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prerequisite, "_WHICH", lambda _name: None)
    monkeypatch.setattr(prerequisite, "_SYSTEM", lambda: "Darwin")
    _no_known_location(monkeypatch)

    with pytest.raises(prerequisite.AwsCliPrerequisiteError) as caught:
        prerequisite.check_aws_cli()

    assert caught.value.code == "aws-cli-missing"
    recovery = "\n".join(caught.value.detail_lines)
    assert "AWSCLIV2.pkg" in recovery
    assert prerequisite.AWS_CLI_INSTALL_DOCS_URL in recovery


def test_install_command_is_chosen_per_operating_system() -> None:
    assert "AWSCLIV2.pkg" in prerequisite._install_command("Darwin")
    assert "awscli-exe-linux" in prerequisite._install_command("Linux")
    assert "AWSCLIV2.msi" in prerequisite._install_command("Windows")
    assert prerequisite._install_command("Haiku") == (
        prerequisite.AWS_CLI_INSTALL_DOCS_URL
    )


def test_installed_but_unreachable_cli_teaches_the_path_fix(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prerequisite, "_WHICH", lambda _name: None)
    monkeypatch.setattr(prerequisite, "_SYSTEM", lambda: "Darwin")
    monkeypatch.setattr(
        prerequisite,
        "_first_known_location",
        lambda: Path("/opt/homebrew/bin/aws"),
    )

    with pytest.raises(prerequisite.AwsCliPrerequisiteError) as caught:
        prerequisite.check_aws_cli()

    assert caught.value.code == "aws-cli-not-on-path"
    recovery = "\n".join(caught.value.detail_lines)
    assert "/opt/homebrew/bin" in recovery
    assert "PATH" in recovery


def test_broken_cli_refuses_with_what_the_executable_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(prerequisite, "_WHICH", lambda _name: "/usr/local/bin/aws")
    monkeypatch.setattr(
        prerequisite,
        "_RUN",
        lambda *_a, **_k: _Result(1, "dyld: Library not loaded"),
    )

    with pytest.raises(prerequisite.AwsCliPrerequisiteError) as caught:
        prerequisite.check_aws_cli()

    assert caught.value.code == "aws-cli-unusable"
    assert "Library not loaded" in "\n".join(caught.value.detail_lines)


def test_hanging_cli_refuses_rather_than_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _timeout(*_args, **_kwargs):
        raise subprocess.TimeoutExpired(cmd="aws --version", timeout=1)

    monkeypatch.setattr(prerequisite, "_WHICH", lambda _name: "/usr/local/bin/aws")
    monkeypatch.setattr(prerequisite, "_RUN", _timeout)

    with pytest.raises(prerequisite.AwsCliPrerequisiteError) as caught:
        prerequisite.check_aws_cli()

    assert caught.value.code == "aws-cli-unusable"


def _refuse(monkeypatch: pytest.MonkeyPatch) -> None:
    def _check():
        raise prerequisite.AwsCliPrerequisiteError(
            "aws-cli-missing",
            "The AWS CLI is not installed on this machine.",
            ("Install it: brew-free installer command", "Verify with: aws --version"),
        )

    monkeypatch.setattr(prerequisite, "check_aws_cli", _check)


def test_aws_preflight_reports_a_ready_machine(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setattr(
        prerequisite,
        "check_aws_cli",
        lambda: prerequisite.AwsCli(
            executable="/usr/local/bin/aws", version="aws-cli/2.34.55",
        ),
    )

    assert aws_adapter.aws_preflight([]) == 0
    assert "/usr/local/bin/aws" in capsys.readouterr().out


def test_aws_preflight_refuses_with_the_recovery_step(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    _refuse(monkeypatch)

    assert aws_adapter.aws_preflight([]) == 127
    err = capsys.readouterr().err
    assert "not installed" in err
    assert "Install it:" in err


def test_aws_exec_refuses_before_running_a_missing_executable(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str],
) -> None:
    fake_deploy_remote = types.SimpleNamespace(
        aws_machine_capability_env=lambda project, region: {"AWS_REGION": region},
    )
    monkeypatch.setattr(
        aws_adapter.importlib, "import_module", lambda _name: fake_deploy_remote,
    )
    monkeypatch.setattr(aws_adapter, "ensure_handlers_loaded", lambda: None)
    monkeypatch.setattr(
        aws_adapter,
        "call_dispatcher",
        lambda **_k: types.SimpleNamespace(
            success=True, result={"settings_json": '{"region": "us-east-1"}'},
            error=None,
        ),
    )

    def _never_runs(*_args, **_kwargs):
        raise AssertionError("a subprocess was started without the AWS CLI")

    monkeypatch.setattr(aws_adapter.subprocess, "run", _never_runs)
    _refuse(monkeypatch)

    assert aws_adapter.aws_exec(["--", "sts", "get-caller-identity"]) == 127
    err = capsys.readouterr().err
    assert "not installed" in err
    assert "Verify with: aws --version" in err


def test_vps_refuses_with_the_named_reason_instead_of_a_traceback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def _never_runs(*_args, **_kwargs):
        raise AssertionError("a subprocess was started without the AWS CLI")

    monkeypatch.setattr(vps_adapter.subprocess, "run", _never_runs)
    _refuse(monkeypatch)

    with pytest.raises(vps_adapter.VpsPowerError) as caught:
        vps_adapter._aws(["ec2", "describe-instances"], {})

    assert "not installed" in str(caught.value)
    assert "Install it:" in str(caught.value)
