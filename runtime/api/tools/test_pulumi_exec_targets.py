"""Exact-stack Pulumi update and resource-target admission regressions."""

from io import StringIO

import pytest

from yoke_core.tools.pulumi_exec import PulumiExecError, execute_pulumi_command
from yoke_core.tools.pulumi_exec_validation import validated_command
from runtime.api.tools.test_pulumi_exec_support import (
    _Child,
    _install_pulumi_project_files,
    _stack_payload,
)


def _urn(stack="app-prod", project="webapp-infra", name="originRolePolicy"):
    return (
        f"urn:pulumi:{stack}::{project}::"
        f"webapp:infra:WebappEnvironmentStack$aws:iam/rolePolicy:RolePolicy::{name}"
    )


@pytest.mark.parametrize("operation", ["preview", "up"])
@pytest.mark.parametrize("stack", ["app-prod", "app-stage"])
def test_targets_preserve_exact_argv_and_capability_authority(
    tmp_path, operation, stack
):
    calls = []
    authority_calls = []
    target = _urn(stack)
    second = _urn(stack, name="anotherPolicy")
    command = [operation, "--stack", stack, "--target", target, f"--target={second}"]
    if operation == "up":
        command.extend(["--yes", "--non-interactive"])

    def aws_loader(project, region, **kwargs):
        authority_calls.append((project, region, kwargs))
        return {}

    def child_factory(argv, **kwargs):
        calls.append((argv, kwargs["env"]))
        return _Child()

    assert (
        execute_pulumi_command(
            "externalwebapp",
            stack,
            command,
            config_loader=lambda project, stack: _stack_payload(project, stack),
            project_root=_install_pulumi_project_files(tmp_path),
            aws_env_loader=aws_loader,
            child_factory=child_factory,
            out=StringIO(),
            err=StringIO(),
        )
        == 0
    )
    assert calls[0][0] == ["pulumi", operation, *command[3:], "--stack", stack]
    assert calls[0][1]["PULUMI_BACKEND_URL"].startswith("s3://yoke-state")
    assert authority_calls[0][0] == "externalwebapp"
    assert authority_calls[0][1:] == ("us-east-1", {"capability_type": "aws-admin"})


@pytest.mark.parametrize(
    "target",
    [
        "",
        "resource",
        "urn:pulumi:app-prod::webapp-infra::aws:iam/rolePolicy:RolePolicy",
        _urn(name=""),
        _urn(name="*"),
        _urn(name="origin?Policy"),
        _urn(name="origin[Policy]"),
        _urn(name="bad name"),
        _urn().replace("aws:iam/rolePolicy:RolePolicy", "aws:iam/rolePolicy"),
        _urn().replace("$aws", "$$aws"),
        _urn().replace("urn:pulumi:", "urn:other:"),
        _urn() + "::extra",
        _urn(name="bad\x00name"),
    ],
)
@pytest.mark.parametrize("operation", ["preview", "up"])
def test_malformed_targets_refuse_before_config_or_child(tmp_path, target, operation):
    with pytest.raises(PulumiExecError, match="pulumi_target_invalid"):
        execute_pulumi_command(
            "externalwebapp",
            "app-prod",
            [operation, "--target", target],
            config_loader=lambda *args: pytest.fail("fetched configuration"),
            project_root=tmp_path,
            child_factory=lambda *args, **kwargs: pytest.fail("launched Pulumi"),
        )


@pytest.mark.parametrize("operation", ["preview", "up"])
def test_missing_and_cross_stack_targets_refuse_before_config(tmp_path, operation):
    for args, reason in [
        (["--target"], "pulumi_target_missing"),
        (["--target="], "pulumi_target_invalid"),
        (["--target", "--diff"], "pulumi_target_invalid"),
        (["--target", _urn("app-stage")], "pulumi_target_stack_mismatch"),
        ([f"--target={_urn('app-stage')}"], "pulumi_target_stack_mismatch"),
    ]:
        with pytest.raises(PulumiExecError, match=reason):
            execute_pulumi_command(
                "externalwebapp",
                "app-prod",
                [operation, *args],
                config_loader=lambda *args: pytest.fail("fetched configuration"),
                project_root=tmp_path,
            )


@pytest.mark.parametrize("operation", ["preview", "up"])
def test_cross_project_target_refuses_before_credentials_or_child(tmp_path, operation):
    command = [operation, "--target", _urn(project="externalwebapp")]
    if operation == "up":
        command.extend(["--yes", "--non-interactive"])
    with pytest.raises(PulumiExecError, match="pulumi_target_project_mismatch"):
        execute_pulumi_command(
            "externalwebapp",
            "app-prod",
            command,
            config_loader=lambda project, stack: _stack_payload(project, stack),
            project_root=_install_pulumi_project_files(tmp_path),
            aws_env_loader=lambda *args, **kwargs: pytest.fail("resolved credentials"),
            child_factory=lambda *args, **kwargs: pytest.fail("launched Pulumi"),
        )


@pytest.mark.parametrize("flags", [[], ["--yes"], ["--non-interactive"]])
def test_targeted_up_retains_confirmation_requirement(flags):
    with pytest.raises(PulumiExecError, match="requires --yes and --non-interactive"):
        validated_command("app-prod", ["up", "--target", _urn(), *flags])


@pytest.mark.parametrize(
    "command",
    [
        ["refresh", "--target", _urn()],
        ["preview", "--target-dependents"],
        ["preview", "--replace", _urn()],
    ],
)
def test_targeting_does_not_admit_other_operations_or_expansion(command):
    with pytest.raises(PulumiExecError, match="not allowed"):
        validated_command("app-prod", command)


@pytest.mark.parametrize(
    "declaration,reason",
    [
        ("runtime: python\n", "pulumi_target_project_missing"),
        ("name: [broken\n", "pulumi_target_project_invalid"),
    ],
)
def test_target_requires_valid_rendered_project_name(tmp_path, declaration, reason):
    root = _install_pulumi_project_files(tmp_path)
    (root / "infra" / "Pulumi.yaml").write_text(declaration)
    with pytest.raises(PulumiExecError, match=reason):
        execute_pulumi_command(
            "externalwebapp",
            "app-prod",
            ["preview", "--target", _urn()],
            config_loader=lambda project, stack: _stack_payload(project, stack),
            project_root=root,
            aws_env_loader=lambda *args, **kwargs: pytest.fail("resolved credentials"),
        )


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
                "yoke",
                "yoke-infra",
                command,
                config_loader=lambda project, stack: _stack_payload(project, stack),
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
            "up",
            "--yes",
            "--non-interactive",
            "--refresh",
            "--suppress-outputs",
            "--diff",
        ],
        config_loader=lambda project, stack: _stack_payload(project, stack),
        project_root=_install_pulumi_project_files(tmp_path),
        aws_env_loader=lambda *args, **kwargs: {},
        child_factory=child_factory,
        out=StringIO(),
        err=StringIO(),
    )

    assert rc == 0
    assert commands == [
        [
            "pulumi",
            "up",
            "--yes",
            "--non-interactive",
            "--refresh",
            "--suppress-outputs",
            "--diff",
            "--stack",
            "yoke-infra",
        ]
    ]


def test_up_rejects_unapproved_target_expansion(tmp_path):
    with pytest.raises(PulumiExecError, match="not allowed"):
        execute_pulumi_command(
            "yoke",
            "yoke-infra",
            ["up", "--yes", "--non-interactive", "--target-dependents"],
            config_loader=lambda project, stack: _stack_payload(project, stack),
            project_root=tmp_path,
        )


def test_mismatched_child_stack_and_payload_identity_refuse(tmp_path):
    with pytest.raises(PulumiExecError, match="child --stack"):
        execute_pulumi_command(
            "yoke",
            "yoke-infra",
            ["preview", "--stack", "prod"],
            config_loader=lambda project, stack: _stack_payload(project, stack),
            project_root=tmp_path,
        )
    with pytest.raises(PulumiExecError, match="identity does not match"):
        execute_pulumi_command(
            "yoke",
            "yoke-infra",
            ["preview"],
            config_loader=lambda project, stack: _stack_payload(project, "stage"),
            project_root=tmp_path,
        )
