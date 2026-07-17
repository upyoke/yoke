"""Typed local Pulumi execution boundary tests."""

from __future__ import annotations

from io import BytesIO, StringIO
from pathlib import Path
import stat

import pytest

from yoke_core.tools.pulumi_exec import PulumiExecError, execute_pulumi_command


class _Child:
    def __init__(self, stdout: bytes = b"preview-ok\n") -> None:
        self.stdout = BytesIO(stdout)
        self.stderr = BytesIO(b"")

    def wait(self, timeout=None):
        del timeout
        return 0


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


@pytest.mark.parametrize("operation", ["up", "destroy", "state-delete", "bash"])
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


def test_github_authority_uses_bound_project_and_both_token_names(tmp_path):
    payload = _payload()
    payload["authority"].update({
        "github_project": "platform",
        "github_repo": "upyoke/platform",
        "github_permissions": {
            "metadata": "read",
            "actions_variables": "write",
        },
    })
    seen = {}

    def auth_loader(project, **kwargs):
        seen["project"] = project
        seen["permissions"] = kwargs["required_permissions"]
        return type("Auth", (), {
            "token": "token-value",
            "repo": "upyoke/platform",
        })()

    def child_factory(command, **kwargs):
        seen["env"] = kwargs["env"]
        return _Child()

    execute_pulumi_command(
        "yoke", "yoke-infra", ["preview"],
        config_loader=lambda project, stack: payload,
        project_root=Path(__file__).resolve().parents[3],
        aws_env_loader=lambda *args, **kwargs: {},
        github_auth_loader=auth_loader,
        child_factory=child_factory,
        out=StringIO(),
        err=StringIO(),
    )
    assert seen["project"] == "platform"
    assert seen["permissions"]["actions_variables"] == "write"
    assert seen["env"]["GITHUB_TOKEN"] == "token-value"
    assert seen["env"]["RUNNER_FLEET_GITHUB_TOKEN"] == "token-value"
