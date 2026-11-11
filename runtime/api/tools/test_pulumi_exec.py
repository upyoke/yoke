"""Typed local Pulumi execution boundary tests."""

from __future__ import annotations

from io import StringIO
from pathlib import Path
import stat

import pytest

from yoke_core.tools.pulumi_exec import PulumiExecError
from runtime.api.tools.pulumi_exec_support_test_support import (
    PROVIDER,
    STACK,
    _Child,
    _execute,
    _file_project,
    _init_settings,
)

_INIT = ["init", "--secrets-provider", PROVIDER]


def test_init_is_pinned_to_kms_key_with_ephemeral_authority(tmp_path):
    calls = []
    encrypted_key = "generated-encrypted-material"

    def child_factory(command, **kwargs):
        cwd = Path(kwargs["cwd"])
        stack_path = cwd / f"Pulumi.{STACK}.yaml"
        stack_path.write_text(
            f"secretsprovider: {PROVIDER}\nencryptedkey: {encrypted_key}\n"
            + stack_path.read_text()
        )
        temp_root = cwd.parents[1]
        calls.append(
            {
                "command": command,
                "temp_root": temp_root,
                "temp_mode": stat.S_IMODE(temp_root.stat().st_mode),
                "env": kwargs["env"],
            }
        )
        return _Child(f"initialized {encrypted_key}\n".encode())

    output = StringIO()
    rc = _execute(
        _file_project(tmp_path),
        _INIT,
        aws_env_loader=lambda *args, **kwargs: {
            "AWS_ACCESS_KEY_ID": "access-key",
            "AWS_SECRET_ACCESS_KEY": "secret-key",
            "GITHUB_TOKEN": "ambient-github-token",
        },
        child_factory=child_factory,
        out=output,
    )

    assert rc == 0
    assert calls[0]["command"] == [
        "pulumi", "stack", "init", STACK,
        "--secrets-provider", PROVIDER, "--non-interactive",
    ]
    assert calls[0]["temp_mode"] == 0o700
    assert calls[0]["env"]["PULUMI_BACKEND_URL"] == (
        "s3://externalwebapp-pulumi-state?region=us-east-1"
    )
    assert "GITHUB_TOKEN" not in calls[0]["env"]
    assert not calls[0]["temp_root"].exists()
    printed = output.getvalue()
    assert "initialized [REDACTED]" in printed
    assert f"initialized {encrypted_key}" not in printed
    assert f"secretsprovider: {PROVIDER}\nencryptedkey: {encrypted_key}\n" in printed


def _settings_without_state():
    settings = _init_settings()
    settings.capabilities.pop("pulumi-state")
    return settings


@pytest.mark.parametrize(
    ("command", "settings", "message"),
    [
        (["init", f"--secrets-provider={PROVIDER}"], _init_settings(), "requires exactly"),
        (["init", "--secrets-provider", "gcpkms://x"], _init_settings(), "awskms://"),
        (
            ["init", "--secrets-provider", "awskms://alias/other"],
            _init_settings(),
            "does not match capability authority",
        ),
        (_INIT, _settings_without_state(), "no pulumi-state capability"),
        (_INIT, _init_settings(project="other"), "do not match the requested project"),
    ],
)
def test_init_refuses_unsafe_requests_before_child(command, settings, message, tmp_path):
    with pytest.raises(PulumiExecError, match=message):
        _execute(
            _file_project(tmp_path),
            command,
            settings_loader=lambda project: settings,
            child_factory=lambda *a, **kw: pytest.fail("child ran"),
        )


def test_init_child_failure_prints_no_stack_file_lines(tmp_path):
    def child_factory(command, **kwargs):
        stack_path = Path(kwargs["cwd"]) / f"Pulumi.{STACK}.yaml"
        stack_path.write_text(
            f"secretsprovider: {PROVIDER}\nencryptedkey: failed-key\n"
            + stack_path.read_text()
        )
        return _Child(returncode=9, stderr=b"init failed\n")

    out, err = StringIO(), StringIO()
    rc = _execute(
        _file_project(tmp_path), _INIT, child_factory=child_factory, out=out, err=err
    )
    assert rc == 9
    assert "encryptedkey" not in out.getvalue()
    assert "init failed" in err.getvalue()


@pytest.mark.parametrize(
    "command", [["preview"], _INIT, ["stack", "rm", "--yes"], ["bash"]]
)
def test_stack_without_a_checked_in_file_refuses(tmp_path, command):
    root = _file_project(tmp_path, "other-stack")
    with pytest.raises(PulumiExecError) as refusal:
        _execute(
            root,
            command,
            settings_loader=lambda project: pytest.fail("loaded settings"),
            child_factory=lambda *a, **kw: pytest.fail("child ran"),
        )
    message = str(refusal.value)
    assert message.startswith("pulumi_stack_file_missing:")
    assert f"infra/Pulumi.{STACK}.yaml" in message
    assert "init --secrets-provider" in message


def test_preview_forces_stack_uses_owner_only_temp_and_cleans_up(tmp_path):
    calls = []

    def child_factory(command, **kwargs):
        cwd = Path(kwargs["cwd"])
        stack_file = cwd / f"Pulumi.{STACK}.yaml"
        calls.append(
            {
                "command": command,
                "root": cwd.parents[1],
                "root_mode": stat.S_IMODE(cwd.parents[1].stat().st_mode),
                "file_mode": stat.S_IMODE(stack_file.stat().st_mode),
                "env": kwargs["env"],
            }
        )
        return _Child()

    output = StringIO()
    rc = _execute(
        _file_project(tmp_path),
        ["preview", "--refresh", "--non-interactive"],
        child_factory=child_factory,
        out=output,
    )
    assert rc == 0
    assert calls[0]["command"] == [
        "pulumi", "preview", "--refresh", "--non-interactive", "--stack", STACK,
    ]
    assert calls[0]["root_mode"] == 0o700
    assert calls[0]["file_mode"] == 0o600
    assert calls[0]["env"]["PULUMI_BACKEND_URL"].startswith(
        "s3://externalwebapp-pulumi-state"
    )
    assert not calls[0]["root"].exists()
    assert output.getvalue() == "preview-ok\n"


def test_child_output_redacts_encrypted_key_and_token(tmp_path):
    root = _file_project(
        tmp_path,
        stack_text=f"secretsprovider: {PROVIDER}\nencryptedkey: checked-in-key\n",
    )
    out = StringIO()
    rc = _execute(
        root,
        ["preview"],
        aws_env_loader=lambda *a, **kw: {"AWS_SECRET_ACCESS_KEY": "aws-secret"},
        child_factory=lambda *a, **kw: _Child(
            b"key=checked-in-key token=github-token aws=aws-secret\n"
        ),
        out=out,
    )
    assert rc == 0
    assert out.getvalue() == "key=[REDACTED] token=[REDACTED] aws=[REDACTED]\n"


def test_preview_json_output_is_durable_owner_only(tmp_path):
    output = tmp_path / "preview.json"
    rc = _execute(
        _file_project(tmp_path),
        ["preview", "--json-output", str(output)],
        child_factory=lambda command, **kwargs: _Child(b'{"steps":[]}\n'),
    )
    assert rc == 0
    assert output.read_text() == '{"steps":[]}\n'
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


@pytest.mark.parametrize("operation", ["state-delete", "bash"])
def test_disallowed_operations_refuse_before_settings_load(operation, tmp_path):
    with pytest.raises(PulumiExecError, match="allows only"):
        _execute(
            _file_project(tmp_path),
            [operation],
            settings_loader=lambda project: pytest.fail("loaded settings"),
        )


@pytest.mark.parametrize(
    "command",
    [
        ["preview", "--config", "secret=value"],
        ["preview", "--config-file", "Pulumi.prod.yaml"],
        ["preview", "--save-plan", "plan.json"],
        ["refresh", "--config", "secret=value"],
    ],
)
def test_preview_and_refresh_reject_unapproved_arguments(command, tmp_path):
    with pytest.raises(PulumiExecError, match="not allowed"):
        _execute(_file_project(tmp_path), command)
