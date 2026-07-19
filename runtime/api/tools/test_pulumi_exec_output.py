"""Bounded exact-stack Pulumi output read coverage."""

from __future__ import annotations

from io import StringIO

import pytest

from runtime.api.tools.test_pulumi_exec_support import (
    _Child,
    _install_pulumi_project_files,
    _stack_payload,
)
from yoke_core.tools.pulumi_exec import PulumiExecError, execute_pulumi_command


def test_stack_output_reads_one_named_value_from_the_exact_stack(tmp_path) -> None:
    commands: list[list[str]] = []

    def child_factory(command, **kwargs):
        commands.append(command)
        return _Child(b"arn:aws:iam::123456789012:role/example\n")

    output = StringIO()
    result = execute_pulumi_command(
        "externalwebapp",
        "externalwebapp-registry",
        ["stack", "output", "githubActionsDeliveryRoleArn"],
        config_loader=lambda project, stack: _stack_payload(project, stack),
        project_root=_install_pulumi_project_files(tmp_path),
        aws_env_loader=lambda *args, **kwargs: {},
        child_factory=child_factory,
        out=output,
        err=StringIO(),
    )

    assert result == 0
    assert commands == [
        [
            "pulumi",
            "stack",
            "output",
            "githubActionsDeliveryRoleArn",
            "--stack",
            "externalwebapp-registry",
        ]
    ]
    assert output.getvalue() == "arn:aws:iam::123456789012:role/example\n"


@pytest.mark.parametrize(
    "command",
    [
        ["stack"],
        ["stack", "output"],
        ["stack", "ls"],
        ["stack", "output", "role", "extra"],
        ["stack", "output", "role", "--show-secrets"],
        ["stack", "output", "../secret"],
    ],
)
def test_stack_output_refuses_broad_or_secret_revealing_commands(
    command,
    tmp_path,
) -> None:
    with pytest.raises(PulumiExecError, match="stack output|output name"):
        execute_pulumi_command(
            "externalwebapp",
            "externalwebapp-registry",
            command,
            config_loader=lambda project, stack: _stack_payload(project, stack),
            project_root=tmp_path,
        )


def test_stack_output_refuses_a_different_child_stack(tmp_path) -> None:
    with pytest.raises(PulumiExecError, match="child --stack"):
        execute_pulumi_command(
            "externalwebapp",
            "externalwebapp-registry",
            ["stack", "output", "role", "--stack", "other"],
            config_loader=lambda project, stack: _stack_payload(project, stack),
            project_root=tmp_path,
        )
