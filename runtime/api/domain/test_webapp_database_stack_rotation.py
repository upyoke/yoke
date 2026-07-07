"""Tests for the Pulumi Aurora master-secret rotation guard."""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest


class _FakeCreateResult:
    def __init__(self, id_: str, outs: dict):
        self.id = id_
        self.outs = outs


class _FakeDiffResult:
    def __init__(self, changes: bool):
        self.changes = changes


class _FakeUpdateResult:
    def __init__(self, outs: dict):
        self.outs = outs


class _FakeResourceProvider:
    pass


class _FakeResource:
    def __init__(self, provider, name, props, opts=None):
        self.provider = provider
        self.name = name
        self.props = props
        self.opts = opts


class _FakeClient:
    def __init__(self, rotation_enabled: bool):
        self.rotation_enabled = rotation_enabled
        self.cancelled: list[str] = []

    def describe_secret(self, SecretId: str) -> dict:
        return {"RotationEnabled": self.rotation_enabled}

    def cancel_rotate_secret(self, SecretId: str) -> None:
        self.cancelled.append(SecretId)


def _load_database_stack_module(monkeypatch):
    fake_pulumi = types.ModuleType("pulumi")
    fake_pulumi.ComponentResource = object
    fake_pulumi.ResourceOptions = object
    fake_pulumi.Input = object
    fake_pulumi.Output = object
    fake_pulumi.RunError = RuntimeError
    fake_dynamic = types.ModuleType("pulumi.dynamic")
    fake_dynamic.ResourceProvider = _FakeResourceProvider
    fake_dynamic.Resource = _FakeResource
    fake_dynamic.CreateResult = _FakeCreateResult
    fake_dynamic.DiffResult = _FakeDiffResult
    fake_dynamic.UpdateResult = _FakeUpdateResult
    fake_aws = types.ModuleType("pulumi_aws")
    monkeypatch.setitem(sys.modules, "pulumi", fake_pulumi)
    monkeypatch.setitem(sys.modules, "pulumi.dynamic", fake_dynamic)
    monkeypatch.setitem(sys.modules, "pulumi_aws", fake_aws)

    repo_root = Path(__file__).resolve().parents[3]
    path = repo_root / "templates" / "webapp" / "infra" / "webapp_database_stack.py"
    spec = importlib.util.spec_from_file_location("_webapp_database_stack_test", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    monkeypatch.setitem(sys.modules, "_webapp_database_stack_test", module)
    spec.loader.exec_module(module)
    return module


def test_rotation_guard_cancels_enabled_secret(monkeypatch):
    module = _load_database_stack_module(monkeypatch)
    provider = module._MasterSecretRotationDisabledProvider()
    client = _FakeClient(rotation_enabled=True)
    monkeypatch.setattr(provider, "_client", lambda: client)

    result = provider.create({"secret_arn": "arn:test"})

    assert client.cancelled == ["arn:test"]
    assert result.id == "arn:test"
    assert result.outs["rotation_enabled"] is False


def test_rotation_guard_leaves_disabled_secret_alone(monkeypatch):
    module = _load_database_stack_module(monkeypatch)
    provider = module._MasterSecretRotationDisabledProvider()
    client = _FakeClient(rotation_enabled=False)
    monkeypatch.setattr(provider, "_client", lambda: client)

    result = provider.create({"secret_arn": "arn:test"})

    assert client.cancelled == []
    assert result.outs["rotation_enabled"] is False


def test_rotation_guard_update_and_delete_semantics(monkeypatch):
    module = _load_database_stack_module(monkeypatch)
    provider = module._MasterSecretRotationDisabledProvider()
    client = _FakeClient(rotation_enabled=True)
    monkeypatch.setattr(provider, "_client", lambda: client)

    diff = provider.diff(
        "arn:old",
        {"secret_arn": "arn:old"},
        {"secret_arn": "arn:new"},
    )
    update = provider.update(
        "arn:old",
        {"secret_arn": "arn:old"},
        {"secret_arn": "arn:new"},
    )

    assert diff.changes is True
    assert client.cancelled == ["arn:new"]
    assert update.outs["rotation_enabled"] is False
    assert provider.delete("arn:new", {"secret_arn": "arn:new"}) is None


def test_auto_pause_default_and_validation(monkeypatch):
    module = _load_database_stack_module(monkeypatch)
    args = module.WebappDatabaseArgs(
        project_name="yoke",
        environment="prod",
        database_name="yoke_prod",
        master_username="yoke_admin",
        engine_version="16.13",
        vpc_id="vpc-1",
        subnet_ids=["subnet-1"],
        allowed_security_group_ids=["sg-1"],
        min_capacity=0,
        max_capacity=4,
        backup_retention_days=7,
    )

    assert args.seconds_until_auto_pause == 1800
    module._validate_args(args)
    args.seconds_until_auto_pause = 299
    with pytest.raises(RuntimeError):
        module._validate_args(args)
