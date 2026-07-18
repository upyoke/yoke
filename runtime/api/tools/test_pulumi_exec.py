"""Typed local Pulumi execution boundary tests."""

from __future__ import annotations

from io import BytesIO, StringIO
from pathlib import Path
import stat

import pytest

from yoke_core.tools.pulumi_exec import (
    PulumiExecError,
    execute_pulumi_command,
)
from runtime.api.tools.test_pulumi_exec_support import _init_settings


class _Child:
    def __init__(
        self,
        stdout: bytes = b"preview-ok\n",
        *,
        stderr: bytes = b"",
        returncode: int = 0,
    ) -> None:
        self.stdout = BytesIO(stdout)
        self.stderr = BytesIO(stderr)
        self.returncode = returncode

    def wait(self, timeout=None):
        del timeout
        return self.returncode


def _payload(project: str = "yoke", stack: str = "yoke-infra"):
    return {
        "config_schema": 2,
        "project_id": 1,
        "project_slug": project,
        "stack_name": stack,
        "stack_kind": "infra",
        "render_values": {
            "project_name": project,
            "pulumi_infra_stack_name": stack,
        },
        "operator_state": {
            "secrets_provider": "awskms://alias/yoke-pulumi",
            "encrypted_key": "encrypted-material",
        },
        "authority": {
            "aws_capability": "aws-admin",
            "aws_region": "us-east-1",
            "backend_url": "s3://yoke-state?region=us-east-1",
            "github_repo": "",
            "github_api_url": "",
            "github_permissions": {"metadata": "read"},
            "sensitive_paths": [
                "operator_state.secrets_provider",
                "operator_state.encrypted_key",
            ],
        },
    }


def test_init_uses_declared_stack_ephemeral_authority_and_persists_state():
    calls = []
    imports = []
    encrypted_key = "generated-encrypted-material"

    def config_loader(project, stack):
        pytest.fail("init fetched initialized stack config")

    def child_factory(command, **kwargs):
        cwd = Path(kwargs["cwd"])
        stack_path = cwd / "Pulumi.externalwebapp-registry.yaml"
        stack_path.write_text(
            "secretsprovider: "
            "awskms://alias/externalwebapp-pulumi-state?region=us-east-1\n"
            f"encryptedkey: {encrypted_key}\n" + stack_path.read_text()
        )
        temp_root = cwd.parents[1]
        calls.append(
            {
                "command": command,
                "cwd": cwd,
                "temp_root": temp_root,
                "temp_mode": stat.S_IMODE(temp_root.stat().st_mode),
                "env": kwargs["env"],
            }
        )
        return _Child(f"initialized {encrypted_key}\n".encode())

    def state_importer(**kwargs):
        imports.append(kwargs)
        return {"receipt_digest": "receipt-digest"}

    output = StringIO()
    rc = execute_pulumi_command(
        "externalwebapp",
        "externalwebapp-registry",
        [
            "init",
            "--secrets-provider",
            "awskms://alias/externalwebapp-pulumi-state?region=us-east-1",
        ],
        config_loader=config_loader,
        project_root=Path(__file__).resolve().parents[3],
        settings_loader=lambda project: _init_settings(),
        state_importer=state_importer,
        aws_env_loader=lambda *args, **kwargs: {
            "AWS_ACCESS_KEY_ID": "access-key",
            "AWS_SECRET_ACCESS_KEY": "secret-key",
            "GITHUB_TOKEN": "ambient-github-token",
        },
        child_factory=child_factory,
        out=output,
        err=StringIO(),
    )

    assert rc == 0
    assert calls[0]["command"] == [
        "pulumi",
        "stack",
        "init",
        "externalwebapp-registry",
        "--secrets-provider",
        "awskms://alias/externalwebapp-pulumi-state?region=us-east-1",
        "--non-interactive",
    ]
    assert calls[0]["temp_mode"] == 0o700
    assert calls[0]["env"]["PULUMI_BACKEND_URL"] == (
        "s3://externalwebapp-pulumi-state?region=us-east-1"
    )
    assert "GITHUB_TOKEN" not in calls[0]["env"]
    assert not calls[0]["temp_root"].exists()
    assert imports == [
        {
            "project": "externalwebapp",
            "stack_name": "externalwebapp-registry",
            "secrets_provider": ("awskms://alias/externalwebapp-pulumi-state?region=us-east-1"),
            "encrypted_key": encrypted_key,
            "apply": True,
        }
    ]
    assert encrypted_key not in output.getvalue()
    assert "[REDACTED]" in output.getvalue()
    assert "receipt-digest" in output.getvalue()


@pytest.mark.parametrize(
    ("command", "settings", "message"),
    [
        (
            ["init", "--secrets-provider=awskms://alias/example"],
            _init_settings(),
            "requires exactly",
        ),
        (
            ["init", "--secrets-provider", "awskms://alias/other"],
            _init_settings(),
            "does not match capability authority",
        ),
        (
            [
                "init",
                "--secrets-provider",
                "awskms://alias/externalwebapp-pulumi-state?region=us-east-1",
            ],
            _init_settings(stacks=["infra"]),
            "not an exact declared project stack",
        ),
        (
            [
                "init",
                "--secrets-provider",
                "awskms://alias/externalwebapp-pulumi-state?region=us-east-1",
            ],
            _init_settings(
                stack_state={
                    "externalwebapp-registry": {
                        "secrets_provider": "awskms://alias/existing",
                        "encrypted_key": "existing-key",
                    }
                }
            ),
            "already registered",
        ),
    ],
)
def test_init_refuses_unsafe_or_non_bootstrap_requests_before_child(
    command,
    settings,
    message,
):
    child_called = False

    def child_factory(*args, **kwargs):
        nonlocal child_called
        child_called = True
        return _Child()

    with pytest.raises(PulumiExecError, match=message):
        execute_pulumi_command(
            "externalwebapp",
            "externalwebapp-registry",
            command,
            config_loader=lambda *args: pytest.fail("fetched stack config"),
            project_root=Path(__file__).resolve().parents[3],
            settings_loader=lambda project: settings,
            aws_env_loader=lambda *args, **kwargs: {},
            child_factory=child_factory,
        )
    assert child_called is False


def test_init_child_failure_does_not_persist_operator_state():
    persisted = False

    def child_factory(command, **kwargs):
        cwd = Path(kwargs["cwd"])
        stack_path = cwd / "Pulumi.externalwebapp-registry.yaml"
        stack_path.write_text(
            "secretsprovider: "
            "awskms://alias/externalwebapp-pulumi-state?region=us-east-1\n"
            "encryptedkey: failed-key\n" + stack_path.read_text()
        )
        return _Child(returncode=9, stderr=b"init failed\n")

    def state_importer(**kwargs):
        nonlocal persisted
        persisted = True
        return {"receipt_digest": "unexpected"}

    rc = execute_pulumi_command(
        "externalwebapp",
        "externalwebapp-registry",
        [
            "init",
            "--secrets-provider",
            "awskms://alias/externalwebapp-pulumi-state?region=us-east-1",
        ],
        config_loader=lambda *args: pytest.fail("fetched stack config"),
        project_root=Path(__file__).resolve().parents[3],
        settings_loader=lambda project: _init_settings(),
        state_importer=state_importer,
        aws_env_loader=lambda *args, **kwargs: {},
        child_factory=child_factory,
        out=StringIO(),
        err=StringIO(),
    )
    assert rc == 9
    assert persisted is False


def test_preview_forces_stack_uses_owner_only_temp_and_cleans_up(tmp_path):
    calls = []

    def child_factory(command, **kwargs):
        cwd = Path(kwargs["cwd"])
        config = cwd.parents[1] / "stack-config.json"
        calls.append({
            "command": command,
            "cwd": cwd,
            "root": cwd.parents[1],
            "config_mode": stat.S_IMODE(config.stat().st_mode),
            "env": kwargs["env"],
        })
        return _Child()

    output = StringIO()
    rc = execute_pulumi_command(
        "yoke",
        "yoke-infra",
        ["preview", "--refresh", "--non-interactive"],
        config_loader=lambda project, stack: _payload(project, stack),
        project_root=Path(__file__).resolve().parents[3],
        aws_env_loader=lambda *args, **kwargs: {
            "AWS_ACCESS_KEY_ID": "access-key",
            "AWS_SECRET_ACCESS_KEY": "secret-key",
        },
        child_factory=child_factory,
        out=output,
        err=StringIO(),
    )
    assert rc == 0
    assert calls[0]["command"] == [
        "pulumi", "preview", "--refresh", "--non-interactive",
        "--stack", "yoke-infra",
    ]
    assert calls[0]["config_mode"] == 0o600
    assert calls[0]["env"]["PULUMI_BACKEND_URL"].startswith("s3://yoke-state")
    assert not calls[0]["root"].exists()
    assert output.getvalue() == "preview-ok\n"


def test_preview_json_output_is_durable_owner_only(tmp_path):
    output = tmp_path / "preview.json"
    rc = execute_pulumi_command(
        "yoke",
        "yoke-infra",
        ["preview", "--json-output", str(output)],
        config_loader=lambda project, stack: _payload(project, stack),
        project_root=Path(__file__).resolve().parents[3],
        aws_env_loader=lambda *args, **kwargs: {},
        child_factory=lambda command, **kwargs: _Child(b'{"steps":[]}\n'),
        out=StringIO(),
        err=StringIO(),
    )
    assert rc == 0
    assert output.read_text() == '{"steps":[]}\n'
    assert stat.S_IMODE(output.stat().st_mode) == 0o600


@pytest.mark.parametrize("operation", ["destroy", "state-delete", "bash"])
def test_disallowed_operations_refuse_before_config_fetch(operation, tmp_path):
    called = False

    def loader(project, stack):
        nonlocal called
        called = True
        return _payload(project, stack)

    with pytest.raises(PulumiExecError, match="allows only"):
        execute_pulumi_command(
            "yoke", "yoke-infra", [operation],
            config_loader=loader,
            project_root=tmp_path,
        )
    assert called is False


def test_up_requires_explicit_non_interactive_confirmation(tmp_path):
    for command in (
        ["up"],
        ["up", "--yes"],
        ["up", "--non-interactive"],
    ):
        with pytest.raises(
            PulumiExecError,
            match="requires --yes and --non-interactive",
        ):
            execute_pulumi_command(
                "yoke", "yoke-infra", command,
                config_loader=lambda project, stack: _payload(project, stack),
                project_root=tmp_path,
            )


def test_up_uses_exact_stack_and_safe_flags(tmp_path):
    commands = []

    def child_factory(command, **kwargs):
        commands.append(command)
        return _Child(b"update-ok\n")

    rc = execute_pulumi_command(
        "yoke",
        "yoke-infra",
        [
            "up", "--yes", "--non-interactive", "--refresh",
            "--suppress-outputs", "--diff",
        ],
        config_loader=lambda project, stack: _payload(project, stack),
        project_root=Path(__file__).resolve().parents[3],
        aws_env_loader=lambda *args, **kwargs: {},
        child_factory=child_factory,
        out=StringIO(),
        err=StringIO(),
    )

    assert rc == 0
    assert commands == [[
        "pulumi", "up", "--yes", "--non-interactive", "--refresh",
        "--suppress-outputs", "--diff", "--stack", "yoke-infra",
    ]]


def test_up_rejects_unapproved_arguments(tmp_path):
    with pytest.raises(PulumiExecError, match="not allowed"):
        execute_pulumi_command(
            "yoke",
            "yoke-infra",
            ["up", "--yes", "--non-interactive", "--target", "resource"],
            config_loader=lambda project, stack: _payload(project, stack),
            project_root=tmp_path,
        )


def test_mismatched_child_stack_and_payload_identity_refuse(tmp_path):
    with pytest.raises(PulumiExecError, match="child --stack"):
        execute_pulumi_command(
            "yoke", "yoke-infra", ["preview", "--stack", "prod"],
            config_loader=lambda project, stack: _payload(project, stack),
            project_root=tmp_path,
        )
    with pytest.raises(PulumiExecError, match="identity does not match"):
        execute_pulumi_command(
            "yoke", "yoke-infra", ["preview"],
            config_loader=lambda project, stack: _payload(project, "stage"),
            project_root=tmp_path,
        )


def test_import_accepts_only_safe_file_form(tmp_path):
    import_file = tmp_path / "imports.json"
    import_file.write_text("{}")
    with pytest.raises(PulumiExecError, match="argument is not allowed"):
        execute_pulumi_command(
            "yoke", "yoke-infra", ["import", "aws:s3/bucket", "name"],
            config_loader=lambda project, stack: _payload(project, stack),
            project_root=tmp_path,
        )
    commands = []

    def child_factory(command, **kwargs):
        commands.append(command)
        return _Child()

    execute_pulumi_command(
        "yoke",
        "yoke-infra",
        [
            "import", "--file", str(import_file), "--protect=false",
            "--generate-code=false", "--yes", "--non-interactive",
        ],
        config_loader=lambda project, stack: _payload(project, stack),
        project_root=Path(__file__).resolve().parents[3],
        aws_env_loader=lambda *args, **kwargs: {},
        child_factory=child_factory,
        out=StringIO(),
        err=StringIO(),
    )
    assert commands[0][-2:] == ["--stack", "yoke-infra"]


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
        execute_pulumi_command(
            "yoke", "yoke-infra", command,
            config_loader=lambda project, stack: _payload(project, stack),
            project_root=tmp_path,
        )


def test_import_requires_exactly_one_file(tmp_path):
    with pytest.raises(PulumiExecError, match="exactly one"):
        execute_pulumi_command(
            "yoke", "yoke-infra",
            ["import", "--file", "one.json", "--file", "two.json"],
            config_loader=lambda project, stack: _payload(project, stack),
            project_root=tmp_path,
        )
