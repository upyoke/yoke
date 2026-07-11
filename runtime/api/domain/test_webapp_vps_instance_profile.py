"""VPS instance-profile wiring and AMI-drift behavior."""

from __future__ import annotations

from runtime.api.domain.test_webapp_registry_stack import (
    _load_template_module,
    _Recorder,
)


def _vps_stack(monkeypatch, **arg_overrides):
    recorder = _Recorder()
    module = _load_template_module(monkeypatch, recorder, "webapp_vps_stack.py")
    kwargs = dict(
        deploy_namespace="buzz",
        instance_type="t4g.medium",
        root_volume_gb=40,
        ssh_key_name="buzz-key",
        stack_name="buzz-vps",
    )
    kwargs.update(arg_overrides)
    stack = module.WebappVpsStack("buzz-vps", module.WebappVpsArgs(**kwargs))
    return recorder, stack


def test_default_keeps_instance_profile_absent(monkeypatch):
    recorder, _stack = _vps_stack(monkeypatch)
    instance = recorder.single("vpsInstance")
    assert instance.kwargs["iam_instance_profile"] is None


def test_provided_profile_lands_on_instance(monkeypatch):
    recorder, _stack = _vps_stack(
        monkeypatch, iam_instance_profile_name="origin-profile",
    )
    instance = recorder.single("vpsInstance")
    assert instance.kwargs["iam_instance_profile"] == "origin-profile"


def test_instance_ignores_ami_drift(monkeypatch):
    recorder, stack = _vps_stack(monkeypatch)
    instance = recorder.single("vpsInstance")
    assert instance.opts.ignore_changes == ["ami"]
    assert instance.opts.parent is stack
