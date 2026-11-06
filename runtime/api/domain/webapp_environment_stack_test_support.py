# ruff: noqa: F401, E402
"""Shared setup for tests in this directory."""

from __future__ import annotations

import json

import types

from runtime.api.domain.webapp_registry_stack_test_support import (
    _load_pack_module,
    _Recorder,
)


def _recording_args_class():
    class _RecordingArgs:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    return _RecordingArgs


def _fake_sibling_modules(recorder):
    database = types.ModuleType("webapp_database_stack")
    database.DEFAULT_SECONDS_UNTIL_AUTO_PAUSE = 1800

    class _FakeDatabaseStack:
        def __init__(self, name, args, opts=None):
            self.resource_type = "fake:WebappDatabaseStack"
            self.resource_name = name
            self.args = args
            self.cluster = types.SimpleNamespace(endpoint="db.internal.example")
            self.master_secret_arn = (
                "arn:aws:secretsmanager:us-east-1:123456789012:secret:yoke-prod-db"
            )
            recorder.resources.append(self)

    database.WebappDatabaseArgs = _recording_args_class()
    database.WebappDatabaseStack = _FakeDatabaseStack

    api = types.ModuleType("webapp_api_stack")

    class _FakeApiStack:
        def __init__(self, name, args, opts=None):
            self.resource_type = "fake:WebappApiStack"
            self.resource_name = name
            self.args = args
            self.distribution = types.SimpleNamespace(id="distribution-id")
            recorder.resources.append(self)

    api.WebappApiArgs = _recording_args_class()
    api.WebappApiStack = _FakeApiStack

    distribution_variables = types.ModuleType("webapp_distribution_github_variables")

    def _create_distribution_variables(**kwargs):
        recorder.distribution_variable_kwargs = kwargs
        prefix = f"{kwargs['variable_namespace']}_{kwargs['environment']}_distribution"
        return tuple(
            types.SimpleNamespace(variable_name=f"{prefix}_{suffix}".upper())
            for suffix in ("base_url", "bucket", "cloudfront_id", "origin_id")
        )

    distribution_variables.create_distribution_variables = (
        _create_distribution_variables
    )

    return {
        "webapp_database_stack": database,
        "webapp_api_stack": api,
        "webapp_distribution_github_variables": distribution_variables,
    }


def _environment_stack(monkeypatch, **arg_overrides):
    recorder = _Recorder()
    recorder.stack_outputs = {
        "yoke-platform-vps": {
            "vpsElasticIpAddress": "198.51.100.7",
            "vpsSecurityGroupId": "sg-fake",
        }
    }
    module = _load_pack_module(
        monkeypatch,
        recorder,
        "webapp_environment_stack.py",
        extra_modules=_fake_sibling_modules(recorder),
    )
    kwargs = dict(
        deploy_namespace="yoke",
        environment="prod",
        domain_name="example.com",
        api_host="api.example.com",
        origin_host="origin.example.com",
        hosted_zone_id="Z123",
        api_origin_port=8100,
        origin_vps_stack_name="yoke-platform-vps",
        origin_vps_elastic_ip_output="vpsElasticIpAddress",
        origin_vps_security_group_output="vpsSecurityGroupId",
        database_name="yoke_prod",
        database_master_username="yoke_admin",
        database_engine_version="16.13",
        database_min_capacity_acu=0.0,
        database_max_capacity_acu=4.0,
        database_backup_retention_days=7,
        database_allowed_security_group_ids=["sg-tenant-provisioner"],
    )
    kwargs.update(arg_overrides)
    stack = module.WebappEnvironmentStack(
        "yoke-prod",
        module.WebappEnvironmentArgs(**kwargs),
    )
    return recorder, stack
