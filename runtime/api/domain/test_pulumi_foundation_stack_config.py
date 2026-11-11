"""Which config namespace the latest Pulumi entrypoint reads each value from.

Runs the latest ``pulumi-foundation`` ``__main__.py`` against a fake
``pulumi`` whose config holds two namespaces: the project's own
``webapp-infra:`` keys from its checked-in stack file, and the ``yoke:``
values ``yoke pulumi exec`` adds. Component stacks are recording fakes, except
the runner fleet's real config reader from the latest self-hosted-runners Pack.
"""

from __future__ import annotations

import json
import runpy
import sys
import types

import pytest

from runtime.api.domain.webapp_pulumi_test_support import _pack_program_source

YOKE = {
    "deploy_namespace": "acme",
    "aws_account_id": "123456789012",
    "kms_key_alias": "alias/acme-state",
    "github_repo_slug": "acme/app",
    "github_api_url": "https://api.github.com",
    "component_type_aliases_json": '{"infra": ["legacy:infra:Edge"]}',
}


class _MissingConfig(RuntimeError):
    pass


class _Config:
    def __init__(self, values: dict, namespace: str) -> None:
        self._values = values
        self._namespace = namespace

    def get(self, key):
        value = self._values.get(key)
        return None if value is None else str(value)

    def require(self, key):
        if key not in self._values:
            raise _MissingConfig(
                f"Missing required configuration variable '{self._namespace}:{key}'"
            )
        return str(self._values[key])

    def get_int(self, key):
        value = self.get(key)
        return None if value is None else int(value)

    def require_int(self, key):
        return int(self.require(key))

    def get_bool(self, key):
        value = self.get(key)
        return None if value is None else value == "true"

    def require_bool(self, key):
        return self.require(key) == "true"

    def get_object(self, key):
        value = self.get(key)
        return None if value is None else json.loads(value)


def _recording_module(name: str, stack_class: str, args_class: str, captured: dict):
    module = types.ModuleType(name)

    class _Args:
        def __init__(self, **kwargs):
            self.__dict__.update(kwargs)

    class _Stack:
        def __init__(self, stack_name, args):
            captured["stack"] = (stack_class, stack_name, args)

    setattr(module, args_class, _Args)
    setattr(module, stack_class, _Stack)
    return module


def _run(monkeypatch, stack: str, project: dict, yoke: dict) -> dict:
    captured: dict = {}
    namespaces = {None: project, "yoke": yoke}
    fake = types.ModuleType("pulumi")
    fake.Config = lambda namespace=None: _Config(
        namespaces[namespace], namespace or "webapp-infra"
    )
    fake.get_stack = lambda: stack
    fake.RunError = RuntimeError
    monkeypatch.setitem(sys.modules, "pulumi", fake)
    monkeypatch.setattr(sys, "path", list(sys.path))
    for name in (
        "webapp_component_aliases",
        "webapp_runner_fleet_stack_config",
        "webapp_runner_fleet_config",
    ):
        monkeypatch.delitem(sys.modules, name, raising=False)
    database = types.ModuleType("webapp_database_stack")
    database.DEFAULT_SECONDS_UNTIL_AUTO_PAUSE = 1800
    records = types.ModuleType("webapp_dns_records")
    records.DomainTxtRecordArgs = records.DomainMxRecordArgs = dict
    policy = types.ModuleType("webapp_registry_delivery_ssm_policy")
    policy.delivery_authority_from_config = lambda raw: ("authority", raw)
    fakes = {
        "webapp_dns_records": records,
        "webapp_database_stack": database,
        "webapp_registry_delivery_ssm_policy": policy,
        "webapp_environment_stack": _recording_module(
            "webapp_environment_stack",
            "WebappEnvironmentStack",
            "WebappEnvironmentArgs",
            captured,
        ),
        "webapp_registry_stack": _recording_module(
            "webapp_registry_stack",
            "WebappRegistryStack",
            "WebappRegistryArgs",
            captured,
        ),
        "webapp_infra_stack": _recording_module(
            "webapp_infra_stack", "WebappInfraStack", "WebappInfraArgs", captured
        ),
        "webapp_runner_fleet_stack": _recording_module(
            "webapp_runner_fleet_stack", "WebappRunnerFleetStack", "unused", captured
        ),
    }
    for name, module in fakes.items():
        monkeypatch.setitem(sys.modules, name, module)
    monkeypatch.syspath_prepend(
        str(_pack_program_source("webapp_runner_fleet_stack_config.py").parent)
    )
    runpy.run_path(str(_pack_program_source("__main__.py")), run_name="__main__")
    return captured


def _environment_project() -> dict:
    return {
        "stack_kind": "environment",
        "domain_name": "example.com",
        "hosted_zone_id": "Z123",
        "database_master_username": "app_admin",
        "database_engine_version": "16.4",
        "database_min_capacity_acu": "0",
        "database_max_capacity_acu": "2",
        "database_backup_retention_days": "7",
        "distribution_repository_variable_namespace": "acme",
    }


def _environment_yoke() -> dict:
    return {
        **YOKE,
        "environment": "prod",
        "api_host": "api.example.com",
        "origin_host": "origin.example.com",
        "api_origin_port": "8100",
        "origin_vps_stack_name": "acme-vps",
        "database_name": "acme_prod",
        "distribution_bucket_name": "acme-prod-web",
    }


def test_environment_reads_yoke_facts_and_project_values(monkeypatch):
    captured = _run(
        monkeypatch, "acme-prod", _environment_project(), _environment_yoke()
    )

    kind, name, args = captured["stack"]
    assert (kind, name) == ("WebappEnvironmentStack", "acme-prod")
    assert args.deploy_namespace == "acme"
    assert (args.environment, args.api_host, args.api_origin_port) == (
        "prod",
        "api.example.com",
        8100,
    )
    assert args.database_name == "acme_prod"
    assert args.database_master_username == "app_admin"
    assert args.distribution_repository_variable_namespace == "acme"
    assert args.github_repo == "acme/app"
    # Defaults the old rendered config applied silently, now explicit.
    assert args.database_seconds_until_auto_pause == 1800
    assert args.origin_vps_elastic_ip_output == "vpsElasticIpAddress"
    assert args.origin_vps_security_group_output == "vpsSecurityGroupId"
    assert args.database_allowed_security_group_ids == []


def test_environment_master_username_is_project_owned(monkeypatch):
    project = _environment_project()
    username = project.pop("database_master_username")
    yoke = {**_environment_yoke(), "database_master_username": username}

    with pytest.raises(_MissingConfig, match="webapp-infra:database_master_username"):
        _run(monkeypatch, "acme-prod", project, yoke)


def test_environment_variable_namespace_is_project_owned(monkeypatch):
    project = _environment_project()
    namespace = project.pop("distribution_repository_variable_namespace")
    yoke = {
        **_environment_yoke(),
        "distribution_repository_variable_namespace": namespace,
    }

    _kind, _name, args = _run(monkeypatch, "acme-prod", project, yoke)["stack"]
    assert args.distribution_repository_variable_namespace == ""


def test_environment_requires_yoke_environment_facts(monkeypatch):
    yoke = _environment_yoke()
    del yoke["origin_vps_stack_name"]
    with pytest.raises(_MissingConfig, match="yoke:origin_vps_stack_name"):
        _run(monkeypatch, "acme-prod", _environment_project(), yoke)


def test_registry_reads_authority_from_yoke_and_lists_from_project(monkeypatch):
    project = {
        "distribution_bucket_names": '["acme-prod-web"]',
        "manage_github_oidc_provider": "false",
    }
    yoke = {**YOKE, "delivery_authority_json": '{"instance_tags": {"Name": ["box"]}}'}
    _kind, _name, args = _run(monkeypatch, "acme-registry", project, yoke)["stack"]

    assert args.repository_name == "acme-core"
    assert args.github_repo == "acme/app"
    assert args.aws_account_id == "123456789012"
    assert args.kms_key_alias == "alias/acme-state"
    assert args.state_bucket == "acme-pulumi-state"
    assert args.manage_github_oidc_provider is False
    assert args.distribution_bucket_names == ["acme-prod-web"]
    assert args.cloudfront_distribution_ids == []
    assert args.delivery_authority == (
        "authority",
        {"instance_tags": {"Name": ["box"]}},
    )


def test_registry_defaults_match_the_retired_rendered_config(monkeypatch):
    yoke = {"deploy_namespace": "acme"}
    _kind, _name, args = _run(monkeypatch, "acme-registry", {}, yoke)["stack"]

    assert args.manage_github_oidc_provider is True
    assert args.kms_key_alias == "alias/acme-pulumi-state"
    assert args.github_repo == ""
    assert args.delivery_authority == ("authority", None)


def test_infra_reads_component_aliases_from_yoke(monkeypatch):
    project = {
        "domain_name": "example.com",
        "origin_host": "origin.example.com",
        "hosted_zone_id": "Z123",
        "origin_id": "edge-origin",
        "component_type_aliases": '{"infra": ["ignored:Project"]}',
    }
    _kind, _name, args = _run(monkeypatch, "acme-infra", project, YOKE)["stack"]

    assert args.component_type_aliases == ("legacy:infra:Edge",)
    assert args.domain_txt_records == ()


def test_every_stack_requires_yoke_deploy_namespace(monkeypatch):
    with pytest.raises(_MissingConfig, match="yoke:deploy_namespace"):
        _run(monkeypatch, "acme-registry", {"deploy_namespace": "acme"}, {})


def _runner_yoke() -> dict:
    values = {
        "aws_capability": "aws-admin",
        "aws_region": "us-east-1",
        "github_capability": "github",
        "repo": "acme/app",
        "github_repo_owner": "acme",
        "github_repo_name": "app",
        "github_installation_id": "1",
        "github_repository_id": "2",
        "github_app_issuer": "3",
        "github_api_url": "https://api.github.com",
        "github_web_url": "https://github.com",
        "github_private_key_secret_arn": "arn:aws:secretsmanager:us-east-1:1:secret:k",
        "token_broker_function": "acme-runner-fleet-token-broker",
        "labels_json": '["self-hosted","linux","arm64"]',
        "variable_name": "ACME_RUNNER_LABELS",
        "routing_enabled": "false",
        "instance_type": "t4g.large",
        "architecture": "arm64",
        "root_volume_gb": "40",
        "runner_count": "1",
        "max_runner_count": "3",
        "idle_shutdown_minutes": "30",
        "shutdown_mode": "terminate",
        "spot_on_demand_base_capacity": "0",
        "spot_on_demand_percentage_above_base": "0",
        "lifecycle_writers_paused": "false",
        "lifecycle_code_frozen": "false",
        "deployment_ssh_stack_outputs_json": '{"acme-prod": "originElasticIpAddress"}',
        "project": "acme",
    }
    return {**YOKE, **{f"runner_fleet_{key}": value for key, value in values.items()}}


def test_runner_fleet_reads_every_input_from_yoke_runner_values(monkeypatch):
    captured = _run(monkeypatch, "acme-runner-fleet", {}, _runner_yoke())
    _kind, _name, args = captured["stack"]

    assert (args.project, args.deploy_namespace) == ("acme", "acme")
    assert args.aws_region == "us-east-1"
    assert args.runner_labels == ["self-hosted", "linux", "arm64"]
    assert args.routing_enabled is False
    assert (args.runner_count, args.max_runner_count) == (1, 3)
    assert args.deployment_ssh_stack_outputs == {"acme-prod": "originElasticIpAddress"}


def test_runner_fleet_without_runner_fleet_access_fails_naming_the_key(monkeypatch):
    with pytest.raises(_MissingConfig, match="yoke:runner_fleet_project"):
        _run(monkeypatch, "acme-runner-fleet", {}, YOKE)
