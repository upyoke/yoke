"""Operator-confirmed `destroy` and `stack rm` through `yoke pulumi exec`."""

from __future__ import annotations

from io import StringIO

import pytest

from yoke_core.domain.project_renderer_settings import (
    ProjectRendererSettings,
    RendererEnvironmentSettings,
)
from yoke_core.domain.project_renderer_pulumi_stack_config import (
    PulumiStackConfigError,
)
from yoke_core.tools.pulumi_exec import PulumiExecError, execute_pulumi_command
from runtime.api.tools.pulumi_exec_support_test_support import (
    _Child,
    _install_pulumi_project_files,
    _stack_payload,
)


_STATE = {"secrets_provider": "awskms://alias/yoke-pulumi", "encrypted_key": "secret-ciphertext"}
_DESTROY = ["destroy", "--yes", "--non-interactive"]
_STACK_RM = ["stack", "rm", "--yes"]


def _settings(*environments: tuple[str, dict], stack_state=None):
    return ProjectRendererSettings(
        project="yoke",
        deploy_namespace="yoke",
        display_name="Yoke",
        site_id="",
        site_settings={},
        primary_environment=None,
        environments=tuple(
            RendererEnvironmentSettings(id=str(i), name=name, settings={"pulumi": p})
            for i, (name, p) in enumerate(environments)
        ),
        capabilities={"pulumi-state": {"stack_state": stack_state or {}}},
    )


def _run(command, *, stack="yoke-drill-vps", confirm="yoke-drill-vps", **kwargs):
    calls, removals = kwargs.pop("calls", []), kwargs.pop("removals", [])
    returncode = kwargs.pop("returncode", 0)

    def child_factory(argv, **child_kwargs):
        calls.append(argv)
        return _Child(b"child-ok\n", returncode=returncode)

    def remover(**remove_kwargs):
        removals.append(remove_kwargs)
        return {"mode": "removed", "receipt_digest": "digest"}

    kwargs.setdefault("settings_loader", lambda project: _settings())
    kwargs.setdefault("config_loader", _stack_payload)
    return execute_pulumi_command(
        "yoke",
        stack,
        command,
        confirm_destroy=confirm,
        project_root=kwargs.pop("project_root"),
        aws_env_loader=lambda *args, **kw: {},
        child_factory=child_factory,
        stack_state_remover=remover,
        err=StringIO(),
        **kwargs,
    )


def test_destroy_runs_exact_whole_stack_argv(tmp_path):
    calls, out = [], StringIO()
    flags = ["--refresh", "--diff", "--suppress-outputs"]
    rc = _run(
        [*_DESTROY, *flags, "--stack", "yoke-drill-vps"],
        project_root=_install_pulumi_project_files(tmp_path),
        calls=calls,
        out=out,
    )
    assert rc == 0
    assert calls == [
        ["pulumi", "destroy", *_DESTROY[1:], *flags, "--stack", "yoke-drill-vps"]
    ]
    assert out.getvalue() == "child-ok\n"


def test_stack_rm_runs_exact_argv_and_clears_state_on_success(tmp_path):
    calls, removals, out = [], [], StringIO()
    rc = _run(
        _STACK_RM,
        project_root=_install_pulumi_project_files(tmp_path),
        calls=calls,
        removals=removals,
        out=out,
    )
    assert rc == 0
    assert calls == [["pulumi", "stack", "rm", "--yes", "--stack", "yoke-drill-vps"]]
    assert removals == [{"project": "yoke", "stack_name": "yoke-drill-vps"}]
    assert "operator state removed: yoke|yoke-drill-vps|digest" in out.getvalue()


def test_failed_stack_rm_keeps_operator_state(tmp_path):
    calls, removals = [], []
    rc = _run(
        _STACK_RM,
        project_root=_install_pulumi_project_files(tmp_path),
        calls=calls,
        removals=removals,
        returncode=255,
        out=StringIO(),
    )
    assert rc == 255
    assert len(calls) == 1
    assert removals == []


@pytest.mark.parametrize("command", [_DESTROY, _STACK_RM])
@pytest.mark.parametrize(
    "confirm,reason",
    [
        (None, "pulumi_destroy_confirmation_missing"),
        ("yoke-other-vps", "pulumi_destroy_confirmation_mismatch"),
        ("yoke-drill", "pulumi_destroy_confirmation_mismatch"),
    ],
)
def test_destructive_commands_require_exact_confirmation(
    tmp_path, command, confirm, reason
):
    calls, removals = [], []

    def config_loader(project, stack):
        pytest.fail("refused command fetched stack config")

    with pytest.raises(PulumiExecError, match=reason):
        _run(
            command,
            confirm=confirm,
            project_root=tmp_path,
            config_loader=config_loader,
            calls=calls,
            removals=removals,
        )
    assert calls == [] and removals == []


@pytest.mark.parametrize(
    "command",
    [["preview"], ["stack", "output", "vpsPublicIp"], ["init", "--secrets-provider", "awskms://x"]],
)
def test_confirmation_is_refused_on_other_operations(tmp_path, command):
    with pytest.raises(PulumiExecError, match="pulumi_destroy_confirmation_unused"):
        _run(command, project_root=tmp_path)


@pytest.mark.parametrize(
    "command,reason",
    [
        ([*_STACK_RM, "--force"], "pulumi_stack_rm_force_refused"),
        (["stack", "rm", "--force", "--yes"], "pulumi_stack_rm_force_refused"),
        (["stack", "rm", "-f", "--yes"], "pulumi_stack_rm_force_refused"),
        (["stack", "rm"], "requires exactly `stack rm --yes`"),
        (["stack", "rm", "--yes", "yoke-other"], "requires exactly `stack rm --yes`"),
        ([*_DESTROY, "--target", "urn:pulumi:yoke-drill-vps::p::t:m:R::n"], "pulumi_destroy_target_refused"),
        ([*_DESTROY, "--target=urn:pulumi:yoke-drill-vps::p::t:m:R::n"], "pulumi_destroy_target_refused"),
        ([*_DESTROY, "--target-dependents"], "pulumi_destroy_target_refused"),
        ([*_DESTROY, "--exclude-protected"], "not allowed"),
        (["destroy", "--yes"], "requires --yes and --non-interactive"),
        ([*_DESTROY, "--stack", "yoke-other"], "child --stack must match"),
    ],
)
def test_unsafe_destructive_arguments_refuse_before_child(tmp_path, command, reason):
    calls = []
    with pytest.raises(PulumiExecError, match=reason):
        _run(command, project_root=tmp_path, calls=calls)
    assert calls == []


@pytest.mark.parametrize("command", [_DESTROY, _STACK_RM])
def test_undeclared_stack_refuses_before_child(tmp_path, command):
    calls = []

    def config_loader(project, stack):
        raise PulumiStackConfigError(
            f"Pulumi stack {stack!r} is not an exact declared project stack"
        )

    with pytest.raises(PulumiStackConfigError, match="not an exact declared"):
        _run(command, project_root=tmp_path, config_loader=config_loader, calls=calls)
    assert calls == []


_CONSUMER = ("prod", {"stack_name": "yoke-prod", "origin_vps_stack_name": "yoke-drill-vps"})
_STANDALONE = ("drill", {"origin_vps_stack_name": "yoke-drill-vps"})


@pytest.mark.parametrize("command", [_DESTROY, _STACK_RM])
@pytest.mark.parametrize(
    "settings",
    [
        _settings(_STANDALONE, _CONSUMER, stack_state={"yoke-prod": _STATE}),
        _settings(
            ("prod", {**_CONSUMER[1], "encrypted_key": "legacy-ciphertext"}),
        ),
    ],
)
def test_vps_stack_consumed_by_live_environment_stack_refuses(
    tmp_path, command, settings
):
    calls = []
    with pytest.raises(PulumiExecError, match="pulumi_stack_consumed") as raised:
        _run(
            command,
            project_root=tmp_path,
            settings_loader=lambda project: settings,
            config_loader=lambda p, s: pytest.fail("consumed stack fetched config"),
            calls=calls,
        )
    assert "'yoke-prod'" in str(raised.value)
    assert "ciphertext" not in str(raised.value)
    assert calls == []


@pytest.mark.parametrize(
    "settings",
    [
        _settings(_STANDALONE, stack_state={"yoke-drill-vps": _STATE}),
        _settings(_STANDALONE, _CONSUMER, stack_state={"yoke-drill-vps": _STATE}),
    ],
)
def test_standalone_or_retired_consumer_vps_stack_may_be_destroyed(
    tmp_path, settings
):
    calls = []
    rc = _run(
        _DESTROY,
        project_root=_install_pulumi_project_files(tmp_path),
        settings_loader=lambda project: settings,
        calls=calls,
        out=StringIO(),
    )
    assert rc == 0
    assert calls[0][:2] == ["pulumi", "destroy"]
