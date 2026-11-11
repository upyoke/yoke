"""Bounded exact-stack Pulumi output read coverage."""

from __future__ import annotations

from io import StringIO

import pytest

from runtime.api.tools.pulumi_exec_support_test_support import (
    _Child,
    _execute,
    _file_project,
)
from yoke_core.tools.pulumi_exec import PulumiExecError

_STACK = "externalwebapp-registry"


def test_stack_output_reads_one_named_value_from_the_exact_stack(tmp_path) -> None:
    commands: list[list[str]] = []

    def child_factory(command, **kwargs):
        commands.append(command)
        return _Child(b"arn:aws:iam::123456789012:role/example\n")

    output = StringIO()
    result = _execute(
        _file_project(tmp_path, _STACK),
        ["stack", "output", "githubActionsDeliveryRoleArn"],
        stack=_STACK,
        child_factory=child_factory,
        out=output,
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
        _execute(_file_project(tmp_path, _STACK), command, stack=_STACK)


def test_stack_output_refuses_a_different_child_stack(tmp_path) -> None:
    with pytest.raises(PulumiExecError, match="child --stack"):
        _execute(_file_project(tmp_path, _STACK), ["stack", "output", "role", "--stack", "other"], stack=_STACK)
