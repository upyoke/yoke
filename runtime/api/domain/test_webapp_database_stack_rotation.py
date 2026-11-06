"""Tests for the Pulumi Aurora master-secret rotation guard."""

from __future__ import annotations

from runtime.api.domain.webapp_database_stack_rotation_test_support import (
    _FakeCreateResult as _FakeCreateResult,
    _FakeDiffResult as _FakeDiffResult,
    _FakeResource as _FakeResource,
    _FakeResourceProvider as _FakeResourceProvider,
    _FakeUpdateResult as _FakeUpdateResult,
    _load_database_stack_module as _load_database_stack_module,
)


import pytest


class _FakeClient:
    def __init__(self, rotation_enabled: bool):
        self.rotation_enabled = rotation_enabled
        self.cancelled: list[str] = []

    def describe_secret(self, SecretId: str) -> dict:
        return {"RotationEnabled": self.rotation_enabled}

    def cancel_rotate_secret(self, SecretId: str) -> None:
        self.cancelled.append(SecretId)


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
        deploy_namespace="yoke",
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
