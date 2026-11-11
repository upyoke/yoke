"""Exact-stack Pulumi update and resource-target admission regressions."""

import pytest

from yoke_core.tools.pulumi_exec import PulumiExecError
from yoke_core.tools.pulumi_exec_validation import validated_command
from runtime.api.tools.pulumi_exec_support_test_support import (
    _Child,
    _execute,
    _file_project,
    _init_settings,
)


def _root(tmp_path, stack="app-prod"):
    return _file_project(tmp_path, stack, name="webapp-infra")


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
        _execute(
            _root(tmp_path, stack),
            command,
            stack=stack,
            aws_env_loader=aws_loader,
            child_factory=child_factory,
        )
        == 0
    )
    assert calls[0][0] == ["pulumi", operation, *command[3:], "--stack", stack]
    assert calls[0][1]["PULUMI_BACKEND_URL"].startswith("s3://externalwebapp-pulumi-state")
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
def test_malformed_targets_refuse_before_settings_or_child(tmp_path, target, operation):
    with pytest.raises(PulumiExecError, match="pulumi_target_invalid"):
        _execute(
            _root(tmp_path),
            [operation, "--target", target],
            stack="app-prod",
            settings_loader=lambda project: pytest.fail("loaded settings"),
            child_factory=lambda *args, **kwargs: pytest.fail("launched Pulumi"),
        )


@pytest.mark.parametrize("operation", ["preview", "up"])
def test_missing_and_cross_stack_targets_refuse_before_settings(tmp_path, operation):
    for args, reason in [
        (["--target"], "pulumi_target_missing"),
        (["--target="], "pulumi_target_invalid"),
        (["--target", "--diff"], "pulumi_target_invalid"),
        (["--target", _urn("app-stage")], "pulumi_target_stack_mismatch"),
        ([f"--target={_urn('app-stage')}"], "pulumi_target_stack_mismatch"),
    ]:
        with pytest.raises(PulumiExecError, match=reason):
            _execute(
                _root(tmp_path),
                [operation, *args],
                stack="app-prod",
                settings_loader=lambda project: pytest.fail("loaded settings"),
            )


@pytest.mark.parametrize("operation", ["preview", "up"])
def test_cross_project_target_refuses_before_credentials_or_child(tmp_path, operation):
    command = [operation, "--target", _urn(project="externalwebapp")]
    if operation == "up":
        command.extend(["--yes", "--non-interactive"])
    with pytest.raises(PulumiExecError, match="pulumi_target_project_mismatch"):
        _execute(
            _root(tmp_path),
            command,
            stack="app-prod",
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
        ("name: [broken\n", "pulumi_project_file_invalid"),
    ],
)
def test_target_requires_valid_project_name(tmp_path, declaration, reason):
    root = _root(tmp_path)
    (root / "infra" / "Pulumi.yaml").write_text(declaration)
    with pytest.raises(PulumiExecError, match=reason):
        _execute(
            root,
            ["preview", "--target", _urn()],
            stack="app-prod",
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
            _execute(_root(tmp_path), command, stack="app-prod")


def test_up_uses_exact_stack_and_safe_flags(tmp_path):
    commands = []

    def child_factory(command, **kwargs):
        commands.append(command)
        return _Child(b"update-ok\n")

    rc = _execute(
        _root(tmp_path),
        [
            "up",
            "--yes",
            "--non-interactive",
            "--refresh",
            "--suppress-outputs",
            "--diff",
        ],
        stack="app-prod",
        child_factory=child_factory,
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
            "app-prod",
        ]
    ]


def test_up_rejects_unapproved_target_expansion(tmp_path):
    with pytest.raises(PulumiExecError, match="not allowed"):
        _execute(
            _root(tmp_path),
            ["up", "--yes", "--non-interactive", "--target-dependents"],
            stack="app-prod",
        )


def test_mismatched_child_stack_and_settings_project_refuse(tmp_path):
    with pytest.raises(PulumiExecError, match="child --stack"):
        _execute(_root(tmp_path), ["preview", "--stack", "prod"], stack="app-prod")
    with pytest.raises(PulumiExecError, match="do not match the requested project"):
        _execute(
            _root(tmp_path),
            ["preview"],
            stack="app-prod",
            settings_loader=lambda project: _init_settings(project="other"),
            child_factory=lambda *a, **kw: pytest.fail("launched Pulumi"),
        )
