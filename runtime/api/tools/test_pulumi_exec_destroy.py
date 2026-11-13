"""Operator-confirmed `destroy` and `stack rm` through `yoke pulumi exec`."""

from __future__ import annotations

import dataclasses
from io import StringIO
import subprocess

import pytest

from yoke_core.domain.project_renderer_settings import RendererEnvironmentSettings
from yoke_core.tools.pulumi_exec import PulumiExecError
from runtime.api.tools.pulumi_exec_support_test_support import (
    _Child,
    _commit_project,
    _execute,
    _file_project,
    _init_settings,
)


_VPS = "app-drill-vps"
_DESTROY = ["destroy", "--yes", "--non-interactive"]
_STACK_RM = ["stack", "rm", "--yes"]
_PREVIEW = ["destroy", "--preview-only"]


def _settings(*environments: tuple[str, dict]):
    return dataclasses.replace(
        _init_settings(),
        environments=tuple(
            RendererEnvironmentSettings(id=str(i), name=name, settings={"pulumi": p})
            for i, (name, p) in enumerate(environments)
        ),
    )


def _run(tmp_path, command, *, confirm=_VPS, **kwargs):
    calls = kwargs.pop("calls", [])
    returncode = kwargs.pop("returncode", 0)
    root = kwargs.pop("root", None) or _file_project(tmp_path, _VPS)
    if kwargs.pop("commit", True):
        _commit_project(root)

    def child_factory(argv, **child_kwargs):
        calls.append(argv)
        return _Child(b"child-ok\n", returncode=returncode)

    return _execute(
        root,
        command,
        stack=_VPS,
        confirm_destroy=confirm,
        child_factory=child_factory,
        **kwargs,
    )


def test_destroy_runs_exact_whole_stack_argv(tmp_path):
    calls, out = [], StringIO()
    flags = ["--refresh", "--diff", "--suppress-outputs"]
    rc = _run(tmp_path, [*_DESTROY, *flags, "--stack", _VPS], calls=calls, out=out)
    assert rc == 0
    assert calls == [["pulumi", "destroy", *_DESTROY[1:], *flags, "--stack", _VPS]]
    assert out.getvalue() == "child-ok\n"


def test_stack_rm_runs_exact_argv(tmp_path):
    calls, out = [], StringIO()
    rc = _run(tmp_path, _STACK_RM, calls=calls, out=out)
    assert rc == 0
    assert calls == [["pulumi", "stack", "rm", "--yes", "--stack", _VPS]]
    assert out.getvalue() == "child-ok\n"


def test_failed_stack_rm_keeps_child_returncode(tmp_path):
    calls = []
    rc = _run(tmp_path, _STACK_RM, calls=calls, returncode=255)
    assert rc == 255
    assert len(calls) == 1


@pytest.mark.parametrize("command", [_DESTROY, _STACK_RM])
@pytest.mark.parametrize(
    "confirm,reason",
    [
        (None, "pulumi_destroy_confirmation_missing"),
        ("app-other-vps", "pulumi_destroy_confirmation_mismatch"),
        ("app-drill", "pulumi_destroy_confirmation_mismatch"),
    ],
)
def test_destructive_commands_require_exact_confirmation(
    tmp_path, command, confirm, reason
):
    calls = []
    with pytest.raises(PulumiExecError, match=reason):
        _run(
            tmp_path,
            command,
            confirm=confirm,
            settings_loader=lambda project: pytest.fail("loaded settings"),
            calls=calls,
        )
    assert calls == []


@pytest.mark.parametrize(
    "command",
    [["preview"], ["stack", "output", "vpsPublicIp"], ["init", "--secrets-provider", "awskms://x"]],
)
def test_confirmation_is_refused_on_other_operations(tmp_path, command):
    with pytest.raises(PulumiExecError, match="pulumi_destroy_confirmation_unused"):
        _run(tmp_path, command)


@pytest.mark.parametrize(
    "command,reason",
    [
        ([*_STACK_RM, "--force"], "pulumi_stack_rm_force_refused"),
        (["stack", "rm", "--force", "--yes"], "pulumi_stack_rm_force_refused"),
        (["stack", "rm", "-f", "--yes"], "pulumi_stack_rm_force_refused"),
        (["stack", "rm"], "requires exactly `stack rm --yes`"),
        (["stack", "rm", "--yes", "app-other"], "requires exactly `stack rm --yes`"),
        ([*_DESTROY, "--target", f"urn:pulumi:{_VPS}::p::t:m:R::n"], "pulumi_destroy_target_refused"),
        ([*_DESTROY, f"--target=urn:pulumi:{_VPS}::p::t:m:R::n"], "pulumi_destroy_target_refused"),
        ([*_DESTROY, "--target-dependents"], "pulumi_destroy_target_refused"),
        ([*_DESTROY, "--exclude-protected"], "not allowed"),
        (["destroy", "--yes"], "requires --yes and --non-interactive"),
        ([*_DESTROY, "--stack", "app-other"], "child --stack must match"),
    ],
)
def test_unsafe_destructive_arguments_refuse_before_child(tmp_path, command, reason):
    calls = []
    with pytest.raises(PulumiExecError, match=reason):
        _run(tmp_path, command, calls=calls)
    assert calls == []


_CONSUMER = ("prod", {"stack_name": "app-prod", "origin_vps_stack_name": _VPS})
_STANDALONE = ("drill", {"origin_vps_stack_name": _VPS})


def _with_consumer_file(tmp_path, origin_ip=""):
    root = _file_project(tmp_path, _VPS)
    (root / "infra" / "Pulumi.app-prod.yaml").write_text(
        f"config:\n  scratch:origin_ip: {origin_ip!r}\n"
    )
    return root


@pytest.mark.parametrize("command", [_DESTROY, _STACK_RM, _PREVIEW])
def test_vps_stack_consumed_by_checked_in_environment_stack_refuses(
    tmp_path, command
):
    calls = []
    settings = _settings(_STANDALONE, _CONSUMER)
    with pytest.raises(PulumiExecError, match="pulumi_stack_consumed") as raised:
        _run(
            tmp_path,
            command,
            confirm=None if command == _PREVIEW else _VPS,
            root=_with_consumer_file(tmp_path),
            settings_loader=lambda project: settings,
            calls=calls,
        )
    message = str(raised.value)
    assert "'app-prod'" in message
    assert "StackReference" in message
    assert "destroy and remove" not in message
    assert "delete infra/" not in message
    assert calls == []


def test_consumed_vps_stack_still_runs_non_destructive_operations(tmp_path):
    calls = []
    settings = _settings(_CONSUMER)
    rc = _run(
        tmp_path,
        ["preview"],
        confirm=None,
        root=_with_consumer_file(tmp_path),
        settings_loader=lambda project: settings,
        calls=calls,
    )
    assert rc == 0
    assert calls[0][:2] == ["pulumi", "preview"]


@pytest.mark.parametrize(
    "settings",
    [_settings(_STANDALONE), _settings(_STANDALONE, _CONSUMER)],
)
def test_standalone_or_retired_consumer_vps_stack_may_be_destroyed(
    tmp_path, settings
):
    calls = []
    rc = _run(
        tmp_path, _DESTROY, settings_loader=lambda project: settings, calls=calls
    )
    assert rc == 0
    assert calls[0][:2] == ["pulumi", "destroy"]


@pytest.mark.parametrize("command", [_DESTROY, _STACK_RM, _PREVIEW])
def test_selector_only_stack_is_allowed_and_explained(tmp_path, command):
    calls, err = [], StringIO()
    rc = _run(
        tmp_path, command, root=_with_consumer_file(tmp_path, "192.0.2.1"),
        confirm=None if command == _PREVIEW else _VPS,
        settings_loader=lambda project: _settings(_CONSUMER), calls=calls, err=err,
    )
    assert rc == 0
    assert len(calls) == 1
    assert "pulumi_stack_destroy_allowed" in err.getvalue()
    assert "stays in use as the live selector" in err.getvalue()


@pytest.mark.parametrize("origin_ip", ["", "  "])
def test_empty_origin_ip_refuses_as_consumed(tmp_path, origin_ip):
    calls = []
    with pytest.raises(PulumiExecError, match="pulumi_stack_consumed") as raised:
        _run(
            tmp_path, _PREVIEW, confirm=None,
            root=_with_consumer_file(tmp_path, origin_ip),
            settings_loader=lambda project: _settings(_CONSUMER), calls=calls,
        )
    assert "database_enabled" not in str(raised.value)
    assert calls == []


@pytest.mark.parametrize("leftover", ["true", "'false'", "nope"])
def test_set_origin_ip_allows_destroy_whatever_database_enabled_says(
    tmp_path, leftover
):
    root = _with_consumer_file(tmp_path)
    (root / "infra" / "Pulumi.app-prod.yaml").write_text(
        f"config: {{scratch:origin_ip: '192.0.2.1', scratch:database_enabled: {leftover}}}\n"
    )
    err = StringIO()
    assert _run(tmp_path, _PREVIEW, confirm=None, root=root, err=err,
                settings_loader=lambda project: _settings(_CONSUMER)) == 0
    assert "pulumi_stack_destroy_allowed" in err.getvalue()


def test_destroy_preview_needs_no_confirmation_and_cannot_delete(tmp_path):
    calls, err = [], StringIO()
    assert _run(tmp_path, _PREVIEW, confirm=None, calls=calls, err=err) == 0
    assert calls == [["pulumi", "destroy", "--preview-only", "--stack", _VPS]]
    assert "pulumi_stack_destroy_allowed" in err.getvalue()


@pytest.mark.parametrize("flag", ["--yes", "--refresh"])
def test_destroy_preview_refuses_mutation_flags(tmp_path, flag):
    calls = []
    with pytest.raises(PulumiExecError, match="pulumi_destroy_preview_mutation_refused"):
        _run(tmp_path, [*_PREVIEW, flag], confirm=None, calls=calls)
    assert calls == []


@pytest.mark.parametrize("config", [
    "{}", "[]", "{scratch:stack_label: app}",
    "{scratch:origin_ip: null}", "{scratch:origin_ip: 0}",
    "{scratch:origin_ip: {secure: encrypted}}",
    "{other:origin_ip: '192.0.2.1'}", "[broken",
])
def test_missing_or_unparseable_consumer_values_fail_closed(tmp_path, config):
    root = _with_consumer_file(tmp_path)
    (root / "infra" / "Pulumi.app-prod.yaml").write_text(f"config: {config}\n")
    calls = []
    with pytest.raises(PulumiExecError, match="pulumi_stack_consumer_config_invalid"):
        _run(tmp_path, _PREVIEW, confirm=None, root=root,
             settings_loader=lambda project: _settings(_CONSUMER), calls=calls)
    assert calls == []


@pytest.mark.parametrize("declaration", ["name: custom", "name: ''", "[]", "[broken"])
def test_guard_uses_declared_namespace_and_refuses_invalid_declaration(tmp_path, declaration):
    root = _with_consumer_file(tmp_path)
    (root / "infra" / "Pulumi.yaml").write_text(declaration)
    calls = []
    with pytest.raises(PulumiExecError, match="pulumi_stack_consumer_config_invalid"):
        _run(tmp_path, _PREVIEW, confirm=None, root=root,
             settings_loader=lambda project: _settings(_CONSUMER), calls=calls)
    assert calls == []


def test_custom_namespace(tmp_path):
    root = _with_consumer_file(tmp_path)
    (root / "infra" / "Pulumi.yaml").write_text("name: custom\nruntime: python\n")
    (root / "infra" / "Pulumi.app-prod.yaml").write_text(
        "config: {custom:origin_ip: '192.0.2.1'}\n"
    )
    assert _run(tmp_path, _PREVIEW, confirm=None, root=root,
                settings_loader=lambda project: _settings(_CONSUMER)) == 0


_EDIT = "config:\n  scratch:origin_ip: '192.0.2.1'\n"


@pytest.mark.parametrize("command", [_DESTROY, _STACK_RM, _PREVIEW])
@pytest.mark.parametrize("change", ["edit", "untracked", "deleted", "declaration"])
def test_uncommitted_consumer_config_refuses(tmp_path, command, change):
    root = _with_consumer_file(tmp_path)
    consumer = root / "infra" / "Pulumi.app-prod.yaml"
    if change == "untracked":
        consumer.unlink()
    _commit_project(root)
    if change == "deleted":
        consumer.unlink()
    elif change == "declaration":
        (root / "infra" / "Pulumi.yaml").write_text("name: other\n")
    else:
        consumer.write_text(_EDIT)
    calls = []
    with pytest.raises(PulumiExecError, match="pulumi_stack_consumer_uncommitted") as raised:
        _run(tmp_path, command, confirm=None if command == _PREVIEW else _VPS,
             root=root, commit=False, calls=calls,
             settings_loader=lambda project: _settings(_CONSUMER))
    assert "commit or revert the change to the named file" in str(raised.value)
    assert calls == []


def test_committed_origin_ip_edit_allows(tmp_path):
    root = _commit_project(_with_consumer_file(tmp_path))
    (root / "infra" / "Pulumi.app-prod.yaml").write_text(_EDIT)
    err = StringIO()
    assert _run(tmp_path, _DESTROY, root=root, err=err,
                settings_loader=lambda project: _settings(_CONSUMER)) == 0
    assert "stays in use as the live selector" in err.getvalue()


@pytest.mark.parametrize("command", [_DESTROY, _STACK_RM, _PREVIEW])
@pytest.mark.parametrize("init", [False, True])
def test_root_without_commit_refuses_even_without_consumers(tmp_path, command, init):
    root = _file_project(tmp_path, _VPS)
    if init:
        subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    calls = []
    with pytest.raises(PulumiExecError, match="pulumi_stack_consumer_uncommitted: .* not a git checkout"):
        _run(tmp_path, command, confirm=None if command == _PREVIEW else _VPS,
             root=root, commit=False, calls=calls,
             settings_loader=lambda project: _settings(_STANDALONE))
    assert calls == []
